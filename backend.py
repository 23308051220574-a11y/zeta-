import json, os, re, hashlib, math, sqlite3, base64
from datetime import datetime, timedelta
from flask import Flask, request, jsonify
from flask_cors import CORS

app = Flask(__name__)
CORS(app, resources={r"/api/*": {
    "origins": "*",
    "methods": ["GET", "POST", "PUT", "DELETE"],
    "allow_headers": ["Content-Type", "Authorization"]
}})

DB_FILE = 'zeta.db'
os.makedirs('uploads/images', exist_ok=True)

try:
    from geopy.geocoders import Nominatim
    from geopy.distance import geodesic
    geolocator = Nominatim(user_agent="Zeta_v2.0_Chihuahua", timeout=10)
    HAS_GEOPY = True
except:
    geolocator = None
    HAS_GEOPY = False

try:
    from PIL import Image
    from io import BytesIO
    HAS_PIL = True
except:
    HAS_PIL = False


def init_database():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()

    c.execute('''CREATE TABLE IF NOT EXISTS users (
        id TEXT PRIMARY KEY,
        email TEXT UNIQUE NOT NULL,
        name TEXT NOT NULL,
        photo TEXT,
        phone TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        last_login TIMESTAMP,
        reports_count INTEGER DEFAULT 0,
        verified INTEGER DEFAULT 0,
        rating REAL DEFAULT 5.0,
        total_km REAL DEFAULT 0,
        trips_count INTEGER DEFAULT 0
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS reports (
        id TEXT PRIMARY KEY,
        user_id TEXT,
        description TEXT NOT NULL,
        category TEXT NOT NULL,
        severity TEXT NOT NULL,
        lat REAL NOT NULL,
        lon REAL NOT NULL,
        address TEXT,
        images TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        verified INTEGER DEFAULT 0,
        verified_by TEXT,
        verified_at TIMESTAMP,
        status TEXT DEFAULT 'pending',
        upvotes INTEGER DEFAULT 0,
        downvotes INTEGER DEFAULT 0,
        news_source TEXT,
        FOREIGN KEY (user_id) REFERENCES users(id)
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS places (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        type TEXT NOT NULL,
        lat REAL NOT NULL,
        lon REAL NOT NULL,
        address TEXT,
        phone TEXT,
        website TEXT,
        description TEXT,
        images TEXT,
        rating REAL DEFAULT 0,
        total_reviews INTEGER DEFAULT 0,
        price_level INTEGER DEFAULT 2,
        hours TEXT,
        tags TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS reviews (
        id TEXT PRIMARY KEY,
        place_id TEXT NOT NULL,
        user_id TEXT NOT NULL,
        rating INTEGER NOT NULL,
        comment TEXT,
        images TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        helpful_count INTEGER DEFAULT 0,
        FOREIGN KEY (place_id) REFERENCES places(id),
        FOREIGN KEY (user_id) REFERENCES users(id)
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS risk_zones (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        lat REAL NOT NULL,
        lon REAL NOT NULL,
        radius_km REAL NOT NULL,
        level TEXT NOT NULL,
        color TEXT NOT NULL,
        zone_type TEXT NOT NULL,
        active INTEGER DEFAULT 1,
        expires_at TIMESTAMP,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        source TEXT,
        description TEXT,
        incident_count INTEGER DEFAULT 1
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS natural_disasters (
        id TEXT PRIMARY KEY,
        type TEXT NOT NULL,
        lat REAL NOT NULL,
        lon REAL NOT NULL,
        radius_km REAL NOT NULL,
        severity TEXT NOT NULL,
        description TEXT,
        active INTEGER DEFAULT 1,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        expires_at TIMESTAMP,
        source TEXT
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS report_votes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        report_id TEXT NOT NULL,
        user_id TEXT NOT NULL,
        vote_type TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(report_id, user_id),
        FOREIGN KEY (report_id) REFERENCES reports(id),
        FOREIGN KEY (user_id) REFERENCES users(id)
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS zone_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id TEXT NOT NULL,
        zone_level TEXT NOT NULL,
        zone_name TEXT,
        lat REAL NOT NULL,
        lon REAL NOT NULL,
        transited_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        trip_id TEXT,
        FOREIGN KEY (user_id) REFERENCES users(id)
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS security_tips (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        tip_text TEXT NOT NULL,
        tip_category TEXT NOT NULL,
        icon TEXT NOT NULL,
        active INTEGER DEFAULT 1,
        priority INTEGER DEFAULT 1,
        zone_level TEXT
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS trips (
        id TEXT PRIMARY KEY,
        user_id TEXT,
        origin_name TEXT,
        dest_name TEXT,
        origin_lat REAL,
        origin_lon REAL,
        dest_lat REAL,
        dest_lon REAL,
        distance_km REAL,
        duration_min INTEGER,
        transport_mode TEXT,
        risk_level TEXT,
        started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        completed_at TIMESTAMP,
        status TEXT DEFAULT 'active',
        FOREIGN KEY (user_id) REFERENCES users(id)
    )''')

    conn.commit()
    conn.close()

init_database()


def seed_security_tips():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM security_tips")
    if c.fetchone()[0] > 0:
        conn.close()
        return

    tips = [
        ("Evita transitar zonas con círculo negro después de las 10pm.", "general", "⚫", 1, "black"),
        ("Las zonas verdes son tu mejor ruta. Priorízalas siempre.", "general", "🟢", 1, "green"),
        ("Comparte tu ubicación en tiempo real con un familiar.", "general", "📍", 1, None),
        ("Mantén tu teléfono cargado al salir de noche.", "general", "🔋", 2, None),
        ("Activa el modo silencio al entrar a zonas de riesgo.", "general", "🔇", 2, None),
        ("Usa rutas con mayor iluminación aunque sean más largas.", "general", "💡", 1, None),
        ("Conoce de antemano los números de emergencia: 911.", "general", "📞", 1, None),
        ("En zona roja, no te detengas innecesariamente.", "general", "🔴", 1, "red"),
        ("Viaja con la ventana subida en zonas amarillas.", "general", "🟡", 2, "yellow"),
        ("Reporta incidentes anónimamente. Tu info salva vidas.", "general", "📢", 2, None),
        ("De noche, prefiere avenidas principales bien iluminadas.", "nocturno", "🌙", 1, None),
        ("Evita callejones y zonas sin alumbrado público.", "nocturno", "🚫", 1, None),
        ("Comparte tu ruta activa con alguien de confianza.", "nocturno", "🛣️", 1, None),
        ("Si algo se ve mal, confía en tu instinto y cambia de ruta.", "nocturno", "👁️", 1, None),
        ("Mantén las puertas con seguro al manejar.", "vehiculo", "🔒", 1, None),
        ("No dejes objetos visibles en el tablero.", "vehiculo", "🎒", 2, None),
        ("Estaciona en lugares bien iluminados y concurridos.", "vehiculo", "🅿️", 1, None),
        ("Revisa los alrededores antes de bajar de tu vehículo.", "vehiculo", "👀", 1, None),
        ("Mantén el tanque con al menos ¼ de combustible.", "vehiculo", "⛽", 3, None),
        ("Camina con confianza y a paso seguro.", "peatonal", "🚶", 2, None),
        ("Guarda el celular al caminar por zonas de riesgo.", "peatonal", "📵", 1, None),
        ("Prefiere caminar en grupo en horas nocturnas.", "peatonal", "👥", 1, None),
        ("En emergencia, activa el botón SOS de tu celular.", "emergencia", "🆘", 1, None),
        ("Policía municipal Chihuahua: (614) 429-3300.", "emergencia", "👮", 1, None),
        ("Cruz Roja Chihuahua: (614) 415-4545.", "emergencia", "🏥", 1, None),
        ("Marca 911 desde cualquier celular sin saldo.", "emergencia", "🚨", 1, None),
    ]

    for tip in tips:
        c.execute(
            "INSERT INTO security_tips (tip_text, tip_category, icon, priority, zone_level) VALUES (?,?,?,?,?)",
            tip
        )

    conn.commit()
    conn.close()

seed_security_tips()


def seed_chihuahua_places():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM places")
    if c.fetchone()[0] > 0:
        conn.close()
        return

    places = [
        {"id":"p_catedral_001","name":"Catedral Metropolitana de Chihuahua","type":"Templo/Cultura","lat":28.6358,"lon":-106.0773,"address":"Plaza de Armas S/N, Centro Histórico","phone":"+52 614 410 3858","description":"Majestuosa catedral barroca del siglo XVIII, ícono de Chihuahua.","rating":4.8,"total_reviews":2847,"price_level":1,"hours":"Lun-Dom 7:00-20:00","tags":"cultura,historia,turismo,gratuito"},
        {"id":"p_quinta_gameros_002","name":"Quinta Gameros – Museo Regional","type":"Museo","lat":28.6400,"lon":-106.0850,"address":"Paseo Bolívar 401, Centro","phone":"+52 614 416 6684","description":"Mansión art nouveau de 1910, una de las más bellas de México.","rating":4.7,"total_reviews":1923,"price_level":1,"hours":"Mar-Dom 9:00-17:00","tags":"museo,arte,historia,art nouveau"},
        {"id":"p_casa_villa_003","name":"Museo Histórico – Casa Pancho Villa","type":"Museo","lat":28.6320,"lon":-106.0910,"address":"Calle 10a No. 3010, Centro","phone":"+52 614 416 2958","description":"Casa donde vivió Pancho Villa. Museo sobre la Revolución Mexicana.","rating":4.6,"total_reviews":1542,"price_level":1,"hours":"Mar-Dom 9:00-18:00","tags":"museo,revolución,pancho villa,historia"},
        {"id":"p_palacio_gobierno_006","name":"Palacio de Gobierno de Chihuahua","type":"Monumento/Cultura","lat":28.6355,"lon":-106.0768,"address":"Plaza Hidalgo S/N, Centro","phone":"+52 614 429 9500","description":"Sede del gobierno estatal con murales de Aarón Piña Mora.","rating":4.6,"total_reviews":1234,"price_level":1,"hours":"Lun-Vie 8:00-18:00, Sáb-Dom 9:00-17:00","tags":"gobierno,murales,historia,arquitectura,gratuito"},
        {"id":"p_teatro_heroes_009","name":"Teatro de los Héroes","type":"Teatro","lat":28.6382,"lon":-106.0862,"address":"Av. Ocampo y Colón, Centro","phone":"+52 614 415 3236","description":"Principal teatro de Chihuahua, 1200 personas. Sede de ópera, ballet y conciertos.","rating":4.7,"total_reviews":1087,"price_level":2,"hours":"Según programación","tags":"teatro,cultura,eventos,artes escénicas"},
        {"id":"p_plaza_armas_080","name":"Plaza de Armas de Chihuahua","type":"Plaza","lat":28.6357,"lon":-106.0772,"address":"Av. Independencia y Guerrero, Centro","phone":"","description":"La plaza principal de Chihuahua.","rating":4.7,"total_reviews":5432,"price_level":1,"hours":"24 horas","tags":"plaza,centro,catedral,gratuito"},
        {"id":"p_acueducto_079","name":"Acueducto Colonial de Chihuahua","type":"Monumento","lat":28.6280,"lon":-106.0710,"address":"Av. Zarco, Col. Santa Rosa","phone":"","description":"Acueducto del siglo XVIII, único en su tipo en el norte de México.","rating":4.6,"total_reviews":1567,"price_level":1,"hours":"24 horas","tags":"acueducto,colonial,historia,gratuito"},
        {"id":"p_plazuela_hidalgo_078","name":"Plazuela Hidalgo","type":"Monumento","lat":28.6352,"lon":-106.0767,"address":"Calle Aldama y Calle Cuarta, Centro","phone":"","description":"Donde fue ejecutado el Padre Hidalgo en 1811.","rating":4.5,"total_reviews":987,"price_level":1,"hours":"24 horas","tags":"monumento,historia,independencia,gratuito"},
        {"id":"p_la_calesa_012","name":"La Calesa","type":"Restaurante","lat":28.6348,"lon":-106.0882,"address":"Av. Juárez 3300, Zona Centro","phone":"+52 614 410 2828","description":"Cocina tradicional chihuahuense en casona histórica. Machaca y burritos de frijol.","rating":4.6,"total_reviews":2341,"price_level":2,"hours":"Lun-Dom 7:30-22:00","tags":"mexicano,regional,machaca,desayuno"},
        {"id":"p_la_parroquia_015","name":"La Parroquia de Chihuahua","type":"Restaurante","lat":28.6355,"lon":-106.0790,"address":"Calle Libertad 200, Centro","phone":"+52 614 415 6262","description":"Cafetería tradicional frente a la Catedral. Café de olla y gorditas.","rating":4.5,"total_reviews":1876,"price_level":1,"hours":"Lun-Dom 7:00-22:00","tags":"café,desayunos,gorditas,tradicional"},
        {"id":"p_burritos_cano_017","name":"Burritos Cano","type":"Taquería","lat":28.6360,"lon":-106.0910,"address":"Calle 21 No. 2015, Centro","phone":"+52 614 416 0303","description":"Los mejores burritos de frijol y machaca de Chihuahua desde 1952.","rating":4.8,"total_reviews":4521,"price_level":1,"hours":"Lun-Sáb 7:00-15:00","tags":"burritos,machaca,frijol,icónico"},
        {"id":"p_tacos_cunado_016","name":"Tacos El Cuñado","type":"Taquería","lat":28.6410,"lon":-106.0970,"address":"Av. División del Norte 3200, Mirador","phone":"+52 614 414 2255","description":"Tacos de carne asada con tortillas de harina artesanales.","rating":4.7,"total_reviews":3421,"price_level":1,"hours":"Lun-Dom 8:00-18:00","tags":"tacos,carne asada,popular"},
        {"id":"p_gorditas_lily_018","name":"Gorditas Doña Lily","type":"Comida Típica","lat":28.6372,"lon":-106.0870,"address":"Mercado Central, Av. Guerrero","phone":"+52 614 410 0900","description":"Gorditas de harina artesanales con chicharrón, frijoles y rajas.","rating":4.6,"total_reviews":2109,"price_level":1,"hours":"Lun-Dom 7:00-16:00","tags":"gorditas,desayuno,típico,mercado"},
        {"id":"p_100_tortillas_085","name":"Las 100 Tortillas","type":"Comida Típica","lat":28.6388,"lon":-106.0892,"address":"Calle 10 No. 2700, Centro","phone":"+52 614 416 9900","description":"Tortillas de harina artesanales, el orgullo de Chihuahua. También machaca y queso.","rating":4.8,"total_reviews":3456,"price_level":1,"hours":"Lun-Sáb 6:00-14:00","tags":"tortillas,harina,artesanal,típico"},
        {"id":"p_cafe_rio_grande_035","name":"Café Río Grande","type":"Cafetería","lat":28.6370,"lon":-106.0855,"address":"Paseo Bolívar 1100, Centro","phone":"+52 614 416 1222","description":"Café de origen Sierra Tarahumara. Brunch y postres artesanales.","rating":4.6,"total_reviews":1876,"price_level":2,"hours":"Lun-Vie 7:00-21:00, Sáb-Dom 8:00-21:00","tags":"café,brunch,artesanal"},
        {"id":"p_xocoveza_039","name":"Xocoveza Café & Chocolate","type":"Cafetería","lat":28.6406,"lon":-106.0870,"address":"Calle 28 No. 2200, Centro","phone":"+52 614 415 6600","description":"Chocolates de Chihuahua. Croissants, tartas y café de especialidad.","rating":4.7,"total_reviews":987,"price_level":2,"hours":"Lun-Sáb 8:00-21:00","tags":"café artesanal,chocolate,postres"},
        {"id":"p_starbucks_038","name":"Starbucks Plaza de Armas","type":"Cafetería","lat":28.6356,"lon":-106.0771,"address":"Av. Aldama y Plaza de Armas","phone":"+52 614 415 7700","description":"Vista a la Catedral. Bebidas de temporada y wifi gratuito.","rating":4.3,"total_reviews":3456,"price_level":3,"hours":"Lun-Dom 6:30-22:00","tags":"café,wifi,centro"},
        {"id":"p_mariscos_altamira_026","name":"Mariscos Altamira","type":"Marisquería","lat":28.6440,"lon":-106.0985,"address":"Av. Heroico Colegio Militar 3800","phone":"+52 614 414 5678","description":"Camarones al mojo, ceviche y coctel de ostiones frescos.","rating":4.6,"total_reviews":2134,"price_level":3,"hours":"Lun-Dom 11:00-20:00","tags":"mariscos,camarones,ceviche"},
        {"id":"p_arrachera_022","name":"El Rey de la Arrachera","type":"Restaurante","lat":28.6480,"lon":-106.1000,"address":"Blvd. Ortiz Mena 4500, Las Granjas","phone":"+52 614 412 3456","description":"Arrachera asada al carbón. Ambiente ranchero auténtico.","rating":4.6,"total_reviews":1987,"price_level":3,"hours":"Lun-Dom 13:00-23:00","tags":"arrachera,carbón,ranchero"},
        {"id":"p_black_angus_023","name":"Black Angus Steakhouse","type":"Restaurante","lat":28.6520,"lon":-106.1100,"address":"Periférico R. Almada km 5.5","phone":"+52 614 411 7700","description":"Cortes Black Angus certificado. Ambiente sofisticado.","rating":4.7,"total_reviews":1456,"price_level":4,"hours":"Lun-Dom 13:00-23:00","tags":"cortes premium,fine dining,lujo"},
        {"id":"p_burnouts_033","name":"Burnout's Burger","type":"Hamburguesas","lat":28.6445,"lon":-106.0980,"address":"Av. División del Norte 4500","phone":"+52 614 414 7700","description":"Hamburguesas 100% Angus chihuahuense.","rating":4.6,"total_reviews":2897,"price_level":2,"hours":"Lun-Dom 12:00-23:00","tags":"hamburguesas,gourmet,angus"},
        {"id":"p_sushi_nori_031","name":"Sushi Nori","type":"Restaurante Japonés","lat":28.6530,"lon":-106.1080,"address":"Blvd. Ortiz Mena 6200, Campestre","phone":"+52 614 411 8800","description":"Sushi premium. Rolls especiales y sashimi fresco.","rating":4.5,"total_reviews":1245,"price_level":3,"hours":"Lun-Dom 13:00-23:00","tags":"sushi,japonés,premium"},
        {"id":"p_pizza_bona_029","name":"Pizza Bona","type":"Pizzería","lat":28.6460,"lon":-106.0995,"address":"Av. Universidad 4000, Colinas del Sol","phone":"+52 614 413 9900","description":"Pizzas artesanales al horno de leña. La favorita local.","rating":4.4,"total_reviews":3210,"price_level":2,"hours":"Lun-Dom 12:00-23:00","tags":"pizza,horno de leña,local"},
        {"id":"p_fashion_mall_040","name":"Fashion Mall Chihuahua","type":"Centro Comercial","lat":28.6580,"lon":-106.1170,"address":"Blvd. Teófilo Borunda 8401","phone":"+52 614 418 7000","description":"El más moderno de Chihuahua. Liverpool, Sears, Cinemex y más de 200 tiendas.","rating":4.5,"total_reviews":8923,"price_level":3,"hours":"Lun-Dom 10:00-21:00","tags":"compras,cine,moda"},
        {"id":"p_plaza_sendero_043","name":"Plaza Sendero Chihuahua","type":"Centro Comercial","lat":28.6610,"lon":-106.1220,"address":"Blvd. Teófilo Borunda 9200","phone":"+52 614 418 9900","description":"Cinépolis, HEB, tiendas departamentales y food court.","rating":4.6,"total_reviews":6543,"price_level":3,"hours":"Lun-Dom 10:00-22:00","tags":"compras,cinépolis,HEB,moderno"},
        {"id":"p_galerias_041","name":"Galerías Chihuahua","type":"Centro Comercial","lat":28.6490,"lon":-106.1090,"address":"Blvd. Ortiz Mena 6200","phone":"+52 614 411 9000","description":"Familiar y accesible con cine y zona de comida.","rating":4.3,"total_reviews":5671,"price_level":2,"hours":"Lun-Dom 10:00-21:00","tags":"compras,cine,familiar"},
        {"id":"p_parque_rejon_045","name":"Parque El Rejón","type":"Parque","lat":28.6150,"lon":-106.1150,"address":"Av. El Palmar, Col. El Rejón","phone":"+52 614 429 3300","description":"Lago artificial, pista para correr y zona deportiva.","rating":4.4,"total_reviews":3456,"price_level":1,"hours":"Lun-Dom 6:00-22:00","tags":"parque,correr,lago,familia,gratuito"},
        {"id":"p_bosque_urbano_048","name":"Bosque Urbano de Chihuahua","type":"Parque","lat":28.6560,"lon":-106.1200,"address":"Periférico de la Juventud, Zona Norte","phone":"+52 614 429 4000","description":"El pulmón verde de Chihuahua. Senderos, lago y ciclismo.","rating":4.6,"total_reviews":4123,"price_level":1,"hours":"Lun-Dom 5:00-22:00","tags":"parque,ciclismo,lago,gratuito"},
        {"id":"p_parque_franklin_047","name":"Parque Franklin","type":"Parque","lat":28.6490,"lon":-106.1030,"address":"Blvd. Francisco Villa, Quintas del Sol","phone":"","description":"Zona de ejercicio al aire libre, skatepark y canchas deportivas.","rating":4.5,"total_reviews":2109,"price_level":1,"hours":"Lun-Dom 6:00-22:00","tags":"parque,ejercicio,skate,gratuito"},
        {"id":"p_cinepolis_050","name":"Cinépolis Sendero Chihuahua","type":"Cine","lat":28.6615,"lon":-106.1225,"address":"Plaza Sendero, Blvd. Borunda 9200","phone":"+52 800 832 4600","description":"4DX, Macro XE y VIP. Últimos estrenos.","rating":4.5,"total_reviews":6789,"price_level":3,"hours":"Lun-Dom 11:00-23:30","tags":"cine,4DX,VIP,estrenos"},
        {"id":"p_zona_dorada_052","name":"Zona Dorada – Bares","type":"Entretenimiento","lat":28.6430,"lon":-106.0990,"address":"Av. División del Norte, Col. Mirador","phone":"","description":"Bares, cantinas y antros de Chihuahua. Activa de jueves a domingo.","rating":4.2,"total_reviews":8901,"price_level":3,"hours":"Jue-Dom 20:00-04:00","tags":"bares,antros,nocturno"},
        {"id":"p_hotel_holiday_055","name":"Holiday Inn Chihuahua","type":"Hotel","lat":28.6380,"lon":-106.0900,"address":"Escudero 702, Centro","phone":"+52 614 414 3350","description":"4 estrellas en el centro histórico. Alberca, gimnasio y restaurante.","rating":4.5,"total_reviews":2123,"price_level":3,"hours":"Check-in: 15:00 / Check-out: 12:00","tags":"hotel,4 estrellas,centro,alberca"},
        {"id":"p_hyatt_057","name":"Hyatt Place Chihuahua","type":"Hotel","lat":28.6510,"lon":-106.1120,"address":"Blvd. Ortiz Mena 3700, Campestre","phone":"+52 614 442 1234","description":"Rooftop bar, spa y alberca infinity. Zona Campestre.","rating":4.7,"total_reviews":1456,"price_level":4,"hours":"Check-in: 15:00 / Check-out: 12:00","tags":"hotel,lujo,rooftop,spa"},
        {"id":"p_aeropuerto_059","name":"Aeropuerto Internacional Roberto Fierro","type":"Transporte","lat":28.7029,"lon":-105.9645,"address":"Carretera Chihuahua-Cd. Juárez km 20","phone":"+52 614 420 0015","description":"Vuelos a CDMX, Los Ángeles, Dallas, Houston y más.","rating":4.2,"total_reviews":4567,"price_level":2,"hours":"4:00-23:00","tags":"aeropuerto,vuelos,transporte,internacional"},
        {"id":"p_central_camiones_060","name":"Central de Autobuses de Chihuahua","type":"Transporte","lat":28.6480,"lon":-106.0790,"address":"Blvd. Juan Pablo II 4200","phone":"+52 614 420 2386","description":"Rutas a todo México: CDMX, Monterrey, Hermosillo, Torreón y más.","rating":3.9,"total_reviews":3210,"price_level":2,"hours":"24 horas","tags":"autobuses,terminal,viajes"},
        {"id":"p_hospital_central_061","name":"Hospital Central del Estado","type":"Hospital","lat":28.6560,"lon":-106.0950,"address":"Calle Teófilo Borunda 1370","phone":"+52 614 414 2233","description":"Principal hospital público. Urgencias 24 horas y todas las especialidades.","rating":3.8,"total_reviews":2341,"price_level":1,"hours":"24 horas – Urgencias siempre abiertas","tags":"hospital,urgencias,salud,público"},
        {"id":"p_star_medica_062","name":"Star Médica Chihuahua","type":"Hospital","lat":28.6490,"lon":-106.1050,"address":"Av. Heroico Colegio Militar 4430","phone":"+52 614 439 9000","description":"Hospital privado de alta especialidad. Urgencias 24 hrs.","rating":4.5,"total_reviews":1987,"price_level":4,"hours":"24 horas","tags":"hospital,privado,urgencias,salud"},
        {"id":"p_cruz_roja_063","name":"Cruz Roja Chihuahua","type":"Emergencias","lat":28.6430,"lon":-106.0890,"address":"Calle Homero 2019, Col. Obispado","phone":"+52 614 415 4545","description":"Ambulancias, primeros auxilios y emergencias.","rating":4.7,"total_reviews":1234,"price_level":1,"hours":"24 horas","tags":"emergencias,ambulancia,cruz roja,salud"},
        {"id":"p_uach_064","name":"Universidad Autónoma de Chihuahua (UACH)","type":"Universidad","lat":28.6350,"lon":-106.0890,"address":"Escorza 900, Centro","phone":"+52 614 439 1500","description":"Principal universidad pública del estado. Más de 35,000 estudiantes.","rating":4.4,"total_reviews":5678,"price_level":1,"hours":"Lun-Vie 7:00-21:00","tags":"universidad,pública,educación"},
        {"id":"p_tec_chihuahua_067","name":"Tecnológico de Monterrey Campus Chihuahua","type":"Universidad","lat":28.6650,"lon":-106.1100,"address":"Av. Heroico Colegio Militar 4700","phone":"+52 614 442 2000","description":"Campus Tec de Monterrey. Negocios, ingeniería y humanidades.","rating":4.5,"total_reviews":2876,"price_level":4,"hours":"Lun-Vie 7:00-22:00","tags":"universidad,privada,Tec"},
        {"id":"p_heb_norte_068","name":"HEB Chihuahua Norte","type":"Supermercado","lat":28.6618,"lon":-106.1228,"address":"Plaza Sendero, Blvd. Borunda 9200","phone":"+52 614 418 9999","description":"Farmacia, panadería, carnicería y productos importados.","rating":4.5,"total_reviews":7890,"price_level":2,"hours":"Lun-Dom 6:00-24:00","tags":"supermercado,HEB,farmacia"},
        {"id":"p_walmart_centro_069","name":"Walmart Chihuahua Centro","type":"Supermercado","lat":28.6280,"lon":-106.0720,"address":"Av. División del Norte 2000","phone":"+52 614 416 0800","description":"El más céntrico de la ciudad. Electrónica, ropa y farmacia.","rating":4.1,"total_reviews":9876,"price_level":2,"hours":"Lun-Dom 7:00-23:00","tags":"supermercado,walmart,farmacia"},
        {"id":"p_templo_san_francisco_075","name":"Templo de San Francisco","type":"Templo","lat":28.6340,"lon":-106.0785,"address":"Calle Victoria y Guerrero, Centro","phone":"+52 614 415 2020","description":"Templo franciscano de 1721. Arquitectura barroca con retablos coloniales.","rating":4.5,"total_reviews":876,"price_level":1,"hours":"Lun-Dom 7:00-20:00","tags":"iglesia,colonial,barroco,gratuito"},
        {"id":"p_smart_fit_073","name":"Smart Fit Chihuahua","type":"Gimnasio","lat":28.6540,"lon":-106.1150,"address":"Blvd. Borunda 8000","phone":"+52 800 090 3030","description":"Equipos modernos, clases grupales y peso libre. Abierto 24 hrs.","rating":4.3,"total_reviews":3456,"price_level":2,"hours":"24 horas","tags":"gimnasio,fitness,24hrs"},
        {"id":"p_tarahumara_081","name":"Restaurante Tarahumara","type":"Restaurante","lat":28.6345,"lon":-106.0885,"address":"Calle Aldama 1800, Centro","phone":"+52 614 415 8800","description":"Gastronomía rarámuri auténtica. Pinole, tejuino y gorditas de maíz azul.","rating":4.5,"total_reviews":1234,"price_level":2,"hours":"Lun-Sáb 9:00-21:00","tags":"tarahumara,rarámuri,regional,sierra"},
    ]

    for p in places:
        c.execute(
            '''INSERT OR IGNORE INTO places
            (id, name, type, lat, lon, address, phone, description,
             rating, total_reviews, price_level, hours, tags)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)''',
            (p['id'], p['name'], p['type'], p['lat'], p['lon'],
             p.get('address',''), p.get('phone',''), p.get('description',''),
             p.get('rating',0), p.get('total_reviews',0), p.get('price_level',2),
             p.get('hours',''), p.get('tags',''))
        )

    conn.commit()
    conn.close()
    print(f"✅ {len(places)} lugares de Chihuahua cargados")

seed_chihuahua_places()


def generate_id(prefix=''):
    ts = str(int(datetime.now().timestamp() * 1000))
    rnd = hashlib.md5(os.urandom(16)).hexdigest()[:8]
    return f"{prefix}{ts}_{rnd}"

def validate_email(email):
    return bool(re.match(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$', email))

def validate_text(text, min_len=10, max_len=1000):
    if not text or len(text.strip()) < min_len:
        return False, f"Mínimo {min_len} caracteres"
    if len(text) > max_len:
        return False, f"Máximo {max_len} caracteres"
    spam = [r'https?://', r'www\.', r'[A-Z]{15,}', r'(.)\1{8,}', r'\$\$\$']
    for p in spam:
        if re.search(p, text, re.IGNORECASE):
            return False, "Contenido no permitido detectado"
    if len(text.split()) < 3:
        return False, "Descripción muy corta"
    return True, "OK"

def compress_image(b64_string, max_size=(800, 800), quality=85):
    if not HAS_PIL or not b64_string or not b64_string.startswith('data:image'):
        return b64_string
    try:
        from io import BytesIO
        header, data = b64_string.split(',', 1)
        img_data = base64.b64decode(data)
        img = Image.open(BytesIO(img_data))
        if img.mode in ('RGBA', 'P'):
            img = img.convert('RGB')
        img.thumbnail(max_size, Image.Resampling.LANCZOS)
        out = BytesIO()
        img.save(out, format='JPEG', quality=quality, optimize=True)
        compressed = base64.b64encode(out.getvalue()).decode()
        return f"data:image/jpeg;base64,{compressed}"
    except Exception as e:
        print(f"Compress error: {e}")
        return b64_string

def get_distance(lat1, lon1, lat2, lon2):
    R = 6371
    dLat = math.radians(lat2 - lat1)
    dLon = math.radians(lon2 - lon1)
    a = math.sin(dLat/2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dLon/2)**2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

def get_coordinates_db(location_name):
    if not location_name:
        return None, None
    if ',' in location_name:
        try:
            parts = location_name.split(',')
            lat, lon = float(parts[0].strip()), float(parts[1].strip())
            if 28.0 <= lat <= 29.2 and -107.0 <= lon <= -105.5:
                return lat, lon
        except:
            pass
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    loc = location_name.lower()
    c.execute('SELECT lat, lon FROM places WHERE LOWER(name) LIKE ? OR LOWER(address) LIKE ? LIMIT 1',
              (f'%{loc}%', f'%{loc}%'))
    row = c.fetchone()
    conn.close()
    if row:
        return row[0], row[1]
    if geolocator:
        try:
            loc_result = geolocator.geocode(f"{location_name}, Chihuahua, México", timeout=10)
            if loc_result and 28.0 <= loc_result.latitude <= 29.2:
                return loc_result.latitude, loc_result.longitude
        except:
            pass
    return None, None


ZONE_COLORS = {
    "negro":    "#1a1a1a",
    "rojo":     "#dc2626",
    "amarillo": "#f59e0b",
    "verde":    "#10b981"
}
ZONE_RISK_SCORES = {"negro": 4, "rojo": 3, "amarillo": 2, "verde": 0}


def seed_risk_zones():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM risk_zones")
    if c.fetchone()[0] > 0:
        conn.close()
        return

    zones = [
        ("z_negro_001", "Zona Alta Violencia – Col. Obrera", 28.6200, -106.0880, 1.2, "negro", "homicidio", "Alta concentración de incidentes violentos reportados."),
        ("z_negro_002", "Zona de Riesgo – Blvd. Juan Pablo II S", 28.6100, -106.0750, 1.0, "negro", "robo_violento", "Robos a mano armada frecuentes en horario nocturno."),
        ("z_negro_003", "Sector Violento – Col. Cerro Grande", 28.5980, -106.0620, 1.5, "negro", "homicidio", "Zona de alta peligrosidad, evitar especialmente de noche."),
        ("z_rojo_001", "Alerta – Col. Las Granjas", 28.6480, -106.0400, 1.0, "rojo", "robo", "Robos a negocios y transeúntes."),
        ("z_rojo_002", "Precaución – Zona Centro Noche", 28.6360, -106.0800, 0.8, "rojo", "asalto", "Asaltos a peatones reportados después de las 22h."),
        ("z_rojo_003", "Alerta – Av. División Norte Sur", 28.6180, -106.0750, 0.9, "rojo", "robo_vehiculo", "Robo de vehículos y autopartes."),
        ("z_rojo_004", "Precaución – Col. Tierra Nueva", 28.6050, -106.0650, 1.1, "rojo", "robo", "Colonias periféricas con reportes de asalto."),
        ("z_amarillo_001", "Precaución Moderada – Centro Histórico Tarde", 28.6355, -106.0770, 0.6, "amarillo", "carterismo", "Carteristas en zona turística."),
        ("z_amarillo_002", "Zona Moderada – Mercado Central", 28.6372, -106.0870, 0.5, "amarillo", "robo_menor", "Robos menores en el mercado."),
        ("z_amarillo_003", "Atención – Zona Central de Autobuses", 28.6480, -106.0790, 0.7, "amarillo", "estafa", "Taxistas no autorizados y estafas a viajeros."),
        ("z_amarillo_004", "Moderado – Periférico Sur Nocturno", 28.6100, -106.1100, 0.8, "amarillo", "asalto", "Precaución en horas nocturnas."),
        ("z_amarillo_005", "Atención – Col. Industrial", 28.6460, -106.0990, 0.6, "amarillo", "robo", "Zona industrial con reportes de robo a vehículos."),
        ("z_verde_001", "Zona Segura – Campestre Norte", 28.6600, -106.1200, 1.5, "verde", "zona_segura", "Colonia residencial de baja incidencia delictiva."),
        ("z_verde_002", "Zona Segura – Fashion Mall y alrededores", 28.6575, -106.1165, 1.0, "verde", "zona_segura", "Zona comercial con vigilancia privada."),
        ("z_verde_003", "Zona Segura – Tec de Monterrey área", 28.6640, -106.1090, 0.8, "verde", "zona_segura", "Zona universitaria residencial."),
        ("z_verde_004", "Zona Segura – Colinas del Sol", 28.6500, -106.1060, 1.2, "verde", "zona_segura", "Colonia residencial tranquila."),
        ("z_verde_005", "Zona Segura – Centro Histórico Diurno", 28.6357, -106.0772, 0.7, "verde", "zona_segura", "Plaza de Armas, segura en horario diurno."),
        ("z_verde_006", "Zona Segura – Paseo Bolívar", 28.6395, -106.0848, 0.5, "verde", "zona_segura", "Bulevar con iluminación y presencia policial."),
    ]

    for z in zones:
        zid, name, lat, lon, radius, level, ztype, desc = z
        c.execute(
            '''INSERT OR IGNORE INTO risk_zones
            (id, name, lat, lon, radius_km, level, color, zone_type, active, description, source)
            VALUES (?,?,?,?,?,?,?,?,1,?,?)''',
            (zid, name, lat, lon, radius, level, ZONE_COLORS[level], ztype, desc, "zeta_data")
        )

    conn.commit()
    conn.close()
    print("✅ Zonas de riesgo iniciales cargadas")

seed_risk_zones()


def calculate_risk_at_point(lat, lon):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    max_level = "verde"
    max_score = 0

    c.execute('''SELECT lat, lon, radius_km, level FROM risk_zones
                 WHERE active=1 AND (expires_at IS NULL OR expires_at > ?)''', (datetime.now(),))
    for zlat, zlon, radius, level in c.fetchall():
        dist = get_distance(lat, lon, zlat, zlon)
        if dist <= radius:
            score = ZONE_RISK_SCORES.get(level, 0)
            if score > max_score:
                max_score = score
                max_level = level

    week_ago = datetime.now() - timedelta(days=7)
    c.execute('''SELECT lat, lon, severity FROM reports
                 WHERE verified=1 AND created_at > ? AND status='active' ''', (week_ago,))
    nearby = 0
    for rlat, rlon, severity in c.fetchall():
        if get_distance(lat, lon, rlat, rlon) <= 0.5:
            nearby += 1
            if severity == 'high' and max_score < 3:
                max_score = 3
                max_level = "rojo"
            elif severity == 'medium' and max_score < 2:
                max_score = 2
                max_level = "amarillo"

    if nearby >= 5 and max_level == "verde":
        max_level = "amarillo"

    conn.close()
    return max_level


def get_zone_name_at_point(lat, lon):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('''SELECT name, lat, lon, radius_km, level FROM risk_zones
                 WHERE active=1 ORDER BY radius_km ASC''')
    for name, zlat, zlon, radius, level in c.fetchall():
        if get_distance(lat, lon, zlat, zlon) <= radius:
            conn.close()
            return name, level
    conn.close()
    return None, None


def verify_report_ai(description, category, severity):
    score = 0.5
    credible = ['policía','patrulla','ambulancia','bomberos','accidente','choque',
                'incendio','robo','asalto','inundación','bloqueo','herido','disparo',
                'balacera','persecución','patrullaje']
    uncertain = ['creo','tal vez','parece','supongo','dicen que','me contaron',
                 'escuché','alguien dijo','quizás']
    desc_lower = description.lower()
    for kw in credible:
        if kw in desc_lower:
            score += 0.1
    for kw in uncertain:
        if kw in desc_lower:
            score -= 0.12
    if len(description) > 80:
        score += 0.1
    severe_kws = ['peligro','grave','urgente','herido','fallecido']
    if severity == 'high' and any(k in desc_lower for k in severe_kws):
        score += 0.15
    return round(min(1.0, max(0.0, score)), 2)


# ─────────────────────────────────────────────────────────────
#  ENDPOINTS
# ─────────────────────────────────────────────────────────────

@app.route('/api/auth/register', methods=['POST'])
def register():
    try:
        data = request.json
        email = data.get('email', '').lower().strip()
        name = data.get('name', '').strip()
        photo = data.get('photo', '')
        phone = data.get('phone', '').strip()

        if not email or not validate_email(email):
            return jsonify({"status": "error", "message": "Email inválido"}), 400
        if not name or len(name) < 2:
            return jsonify({"status": "error", "message": "Nombre inválido (mínimo 2 caracteres)"}), 400

        if photo:
            photo = compress_image(photo, max_size=(400, 400), quality=80)

        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute("SELECT id,name,email,photo,reports_count,rating,trips_count FROM users WHERE email=?", (email,))
        existing = c.fetchone()

        if existing:
            user = {
                "id": existing[0], "name": existing[1], "email": existing[2],
                "photo": existing[3], "reports_count": existing[4],
                "rating": existing[5], "trips_count": existing[6]
            }
            c.execute("UPDATE users SET last_login=? WHERE id=?", (datetime.now(), existing[0]))
            conn.commit()
            conn.close()
            return jsonify({"status": "success", "message": "Sesión restaurada", "user": user})

        uid = generate_id('user_')
        c.execute('INSERT INTO users (id,email,name,photo,phone,last_login) VALUES (?,?,?,?,?,?)',
                  (uid, email, name, photo, phone, datetime.now()))
        conn.commit()
        conn.close()

        user = {
            "id": uid, "email": email, "name": name, "photo": photo,
            "phone": phone, "reports_count": 0, "rating": 5.0,
            "trips_count": 0, "verified": False
        }
        return jsonify({"status": "success", "user": user})

    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/api/places/search', methods=['GET'])
def search_places():
    try:
        query = request.args.get('q', '').strip()
        place_type = request.args.get('type', None)
        lat = request.args.get('lat', None)
        lon = request.args.get('lon', None)
        radius = float(request.args.get('radius', 50))

        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()

        if len(query) < 1:
            sql = 'SELECT id,name,type,lat,lon,address,phone,description,rating,total_reviews,price_level,hours,tags FROM places'
            params = []
            if place_type:
                sql += ' WHERE LOWER(type) LIKE ?'
                params.append(f'%{place_type.lower()}%')
            sql += ' ORDER BY rating DESC, total_reviews DESC LIMIT 100'
            c.execute(sql, params)
        else:
            q = query.lower()
            sql = '''SELECT id,name,type,lat,lon,address,phone,description,rating,total_reviews,price_level,hours,tags
                     FROM places
                     WHERE LOWER(name) LIKE ? OR LOWER(description) LIKE ? OR LOWER(address) LIKE ? OR LOWER(tags) LIKE ?'''
            params = [f'%{q}%', f'%{q}%', f'%{q}%', f'%{q}%']
            if place_type:
                sql += ' AND LOWER(type) LIKE ?'
                params.append(f'%{place_type.lower()}%')
            sql += ' ORDER BY rating DESC, total_reviews DESC LIMIT 30'
            c.execute(sql, params)

        places = []
        for row in c.fetchall():
            place = {
                "id": row[0], "name": row[1], "type": row[2],
                "coords": [row[3], row[4]], "lat": row[3], "lon": row[4],
                "address": row[5], "phone": row[6], "description": row[7],
                "rating": row[8], "total_reviews": row[9], "price_level": row[10],
                "hours": row[11], "tags": row[12], "source": "zeta"
            }
            if lat and lon:
                try:
                    dist = get_distance(float(lat), float(lon), row[3], row[4])
                    if dist <= radius:
                        place['distance_km'] = round(dist, 2)
                        places.append(place)
                except:
                    places.append(place)
            else:
                places.append(place)

        conn.close()
        return jsonify(places[:30])

    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/api/places/<place_id>', methods=['GET'])
def get_place(place_id):
    try:
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute(
            'SELECT id,name,type,lat,lon,address,phone,website,description,rating,total_reviews,price_level,hours FROM places WHERE id=?',
            (place_id,)
        )
        row = c.fetchone()
        if not row:
            conn.close()
            return jsonify({"status": "error", "message": "Lugar no encontrado"}), 404

        place = {
            "id": row[0], "name": row[1], "type": row[2],
            "coords": [row[3], row[4]], "lat": row[3], "lon": row[4],
            "address": row[5], "phone": row[6], "website": row[7],
            "description": row[8], "rating": row[9], "total_reviews": row[10],
            "price_level": row[11], "hours": row[12]
        }

        c.execute(
            '''SELECT r.id,r.rating,r.comment,r.images,r.created_at,r.helpful_count,u.name,u.photo
               FROM reviews r LEFT JOIN users u ON r.user_id=u.id
               WHERE r.place_id=? ORDER BY r.created_at DESC LIMIT 50''',
            (place_id,)
        )
        reviews = []
        for r in c.fetchall():
            reviews.append({
                "id": r[0], "rating": r[1], "comment": r[2],
                "images": json.loads(r[3]) if r[3] else [],
                "created_at": r[4], "helpful_count": r[5],
                "user_name": r[6], "user_photo": r[7]
            })
        place['reviews'] = reviews
        conn.close()
        return jsonify({"status": "success", "place": place})

    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/api/places/<place_id>/reviews', methods=['POST'])
def add_review(place_id):
    try:
        data = request.json
        user_id = data.get('user_id')
        rating = data.get('rating')
        comment = data.get('comment', '').strip()
        images = data.get('images', [])

        if not rating or not (1 <= int(rating) <= 5):
            return jsonify({"status": "error", "message": "Calificación inválida (1-5)"}), 400
        if comment:
            valid, msg = validate_text(comment, min_len=10, max_len=500)
            if not valid:
                return jsonify({"status": "error", "message": msg}), 400

        compressed_images = [compress_image(img) for img in images[:3]]

        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute("SELECT id FROM places WHERE id=?", (place_id,))
        if not c.fetchone():
            conn.close()
            return jsonify({"status": "error", "message": "Lugar no encontrado"}), 404

        review_id = generate_id('review_')
        c.execute(
            'INSERT INTO reviews (id,place_id,user_id,rating,comment,images) VALUES (?,?,?,?,?,?)',
            (review_id, place_id, user_id, int(rating), comment, json.dumps(compressed_images))
        )

        c.execute('SELECT AVG(rating), COUNT(*) FROM reviews WHERE place_id=?', (place_id,))
        avg_rating, total = c.fetchone()
        c.execute('UPDATE places SET rating=?, total_reviews=? WHERE id=?',
                  (round(avg_rating, 1), total, place_id))

        conn.commit()
        conn.close()
        return jsonify({
            "status": "success", "review_id": review_id,
            "message": "¡Reseña publicada exitosamente!",
            "new_rating": round(avg_rating, 1), "total_reviews": total
        })

    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/api/zones/risk', methods=['GET'])
def get_risk_zones():
    try:
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute(
            '''SELECT id,name,lat,lon,radius_km,level,color,zone_type,description,incident_count
               FROM risk_zones
               WHERE active=1 AND (expires_at IS NULL OR expires_at > ?)
               ORDER BY CASE level WHEN 'negro' THEN 1 WHEN 'rojo' THEN 2
                                   WHEN 'amarillo' THEN 3 WHEN 'verde' THEN 4 END''',
            (datetime.now(),)
        )
        zones = []
        for row in c.fetchall():
            zones.append({
                "id": row[0], "name": row[1], "lat": row[2], "lon": row[3],
                "radius_km": row[4], "level": row[5], "color": row[6],
                "zone_type": row[7], "description": row[8], "incident_count": row[9]
            })
        conn.close()
        return jsonify({"status": "success", "zones": zones})

    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/api/zones/check', methods=['POST'])
def check_zone():
    try:
        data = request.json
        lat = float(data.get('lat'))
        lon = float(data.get('lon'))
        user_id = data.get('user_id')
        trip_id = data.get('trip_id')

        level = calculate_risk_at_point(lat, lon)
        zone_name, _ = get_zone_name_at_point(lat, lon)

        if user_id:
            conn = sqlite3.connect(DB_FILE)
            c = conn.cursor()
            c.execute(
                'INSERT INTO zone_history (user_id,zone_level,zone_name,lat,lon,trip_id) VALUES (?,?,?,?,?,?)',
                (user_id, level, zone_name, lat, lon, trip_id)
            )
            conn.commit()
            conn.close()

        return jsonify({
            "status": "success",
            "level": level,
            "color": ZONE_COLORS.get(level, "#10b981"),
            "zone_name": zone_name,
            "risk_score": ZONE_RISK_SCORES.get(level, 0),
            "risk": {"level": level, "color": ZONE_COLORS.get(level, "#10b981"), "zone_name": zone_name}
        })

    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/api/zones/add', methods=['POST'])
def add_risk_zone():
    try:
        data = request.json
        zid = generate_id('zone_')
        name = data.get('name', 'Zona de Riesgo')
        lat = float(data.get('lat'))
        lon = float(data.get('lon'))
        radius = float(data.get('radius_km', 0.5))
        level = data.get('level', 'rojo')
        ztype = data.get('zone_type', 'incidente')
        desc = data.get('description', '')
        expires_hours = int(data.get('expires_hours', 48))
        expires = datetime.now() + timedelta(hours=expires_hours)

        if level not in ZONE_COLORS:
            return jsonify({"status": "error", "message": "Nivel inválido. Usa: negro,rojo,amarillo,verde"}), 400

        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute(
            '''INSERT INTO risk_zones
            (id,name,lat,lon,radius_km,level,color,zone_type,description,expires_at,source)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)''',
            (zid, name, lat, lon, radius, level, ZONE_COLORS[level], ztype, desc, expires, 'admin')
        )
        conn.commit()
        conn.close()
        return jsonify({"status": "success", "zone_id": zid, "message": "Zona creada"})

    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/api/zones/history/<user_id>', methods=['GET'])
def get_zone_history(user_id):
    try:
        period = request.args.get('period', 'month')

        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()

        if period == 'month':
            cutoff = datetime.now() - timedelta(days=30)
        elif period == 'year':
            cutoff = datetime.now() - timedelta(days=365)
        else:
            cutoff = datetime(2020, 1, 1)

        c.execute(
            '''SELECT zone_level, zone_name, lat, lon, transited_at
               FROM zone_history WHERE user_id=? AND transited_at > ?
               ORDER BY transited_at DESC LIMIT 500''',
            (user_id, cutoff)
        )

        history = []
        counts = {"negro": 0, "rojo": 0, "amarillo": 0, "verde": 0}
        for row in c.fetchall():
            level = row[0]
            counts[level] = counts.get(level, 0) + 1
            history.append({
                "level": level, "zone_name": row[1],
                "lat": row[2], "lon": row[3], "at": row[4],
                "color": ZONE_COLORS.get(level, "#6b7280")
            })

        c.execute(
            '''SELECT strftime('%Y-%m', transited_at) as month, zone_level, COUNT(*) as cnt
               FROM zone_history WHERE user_id=? AND transited_at > ?
               GROUP BY month, zone_level ORDER BY month DESC LIMIT 60''',
            (user_id, cutoff)
        )
        monthly = {}
        for row in c.fetchall():
            mo = row[0]
            if mo not in monthly:
                monthly[mo] = {"negro": 0, "rojo": 0, "amarillo": 0, "verde": 0}
            monthly[mo][row[1]] = row[2]

        total = sum(counts.values())
        safe_pct = round(counts.get('verde', 0) / total * 100) if total else 0

        conn.close()
        return jsonify({
            "status": "success",
            "period": period,
            "totals": {k: {"count": v, "color": ZONE_COLORS.get(k, "#888")} for k, v in counts.items()},
            "total": total,
            "recent": history[:50],
            "monthly": monthly,
            "safety_score": safe_pct,
            "safe_streak_days": counts.get('verde', 0)
        })

    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/api/history/zones/record', methods=['POST'])
def record_zone():
    try:
        data = request.json
        user_id = data.get('user_id')
        lat = float(data.get('lat', 0))
        lon = float(data.get('lon', 0))
        level = calculate_risk_at_point(lat, lon)
        zone_name, _ = get_zone_name_at_point(lat, lon)

        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute(
            'INSERT INTO zone_history (user_id,zone_level,zone_name,lat,lon) VALUES (?,?,?,?,?)',
            (user_id, level, zone_name, lat, lon)
        )
        conn.commit()
        conn.close()
        return jsonify({"status": "success", "level": level, "zone_name": zone_name})

    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/api/tips/contextual', methods=['POST'])
def tips_contextual():
    try:
        data = request.json
        lat = float(data.get('lat', 28.635))
        lon = float(data.get('lon', -106.077))
        level = calculate_risk_at_point(lat, lon)

        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute(
            '''SELECT tip_text,tip_category,icon FROM security_tips
               WHERE active=1 AND (zone_level=? OR zone_level IS NULL)
               ORDER BY RANDOM() LIMIT 3''',
            (level,)
        )
        tips = [{"tip": r[0], "text": r[0], "category": r[1], "icon": r[2]} for r in c.fetchall()]
        conn.close()
        return jsonify({"status": "success", "tips": tips, "zone_level": level})

    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/api/tips/all', methods=['GET'])
def get_all_tips():
    try:
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute('SELECT tip_text,tip_category,icon,priority FROM security_tips WHERE active=1 ORDER BY priority, RANDOM()')
        tips = [{"text": r[0], "tip": r[0], "category": r[1], "icon": r[2], "priority": r[3]} for r in c.fetchall()]
        conn.close()
        return jsonify({"status": "success", "tips": tips})

    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/api/tips/random', methods=['GET'])
def get_random_tip():
    try:
        zone_level = request.args.get('zone_level', None)
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        if zone_level:
            c.execute(
                'SELECT tip_text,tip_category,icon FROM security_tips WHERE active=1 AND (zone_level=? OR zone_level IS NULL) ORDER BY RANDOM() LIMIT 1',
                (zone_level,)
            )
        else:
            c.execute('SELECT tip_text,tip_category,icon FROM security_tips WHERE active=1 ORDER BY RANDOM() LIMIT 1')
        row = c.fetchone()
        conn.close()
        if not row:
            return jsonify({"status": "error", "message": "No tips available"}), 404
        return jsonify({"status": "success", "tip": {"text": row[0], "category": row[1], "icon": row[2]}})

    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/api/reports/submit', methods=['POST'])
def submit_report():
    try:
        data = request.json
        user_id = data.get('user_id')
        description = data.get('description', '').strip()
        category = data.get('category', 'general')
        severity = data.get('severity', 'low')
        lat = data.get('lat')
        lon = data.get('lon')
        images = data.get('images', [])

        valid, msg = validate_text(description, min_len=15, max_len=1000)
        if not valid:
            return jsonify({"status": "error", "message": msg}), 400
        if not lat or not lon:
            return jsonify({"status": "error", "message": "Ubicación requerida"}), 400

        lat, lon = float(lat), float(lon)
        if not (28.0 <= lat <= 29.2 and -107.0 <= lon <= -105.5):
            return jsonify({"status": "error", "message": "Ubicación fuera del área de servicio"}), 400

        compressed_images = [compress_image(img, max_size=(1200, 1200)) for img in images[:3]]

        address = "Ubicación reportada"
        if geolocator:
            try:
                loc = geolocator.reverse(f"{lat},{lon}", language='es', timeout=5)
                if loc:
                    addr = loc.raw.get('address', {})
                    parts = [addr.get('road', ''), addr.get('suburb', '')]
                    address = ", ".join([p for p in parts if p]) or address
            except:
                pass

        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        report_id = generate_id('report_')
        c.execute(
            '''INSERT INTO reports
            (id,user_id,description,category,severity,lat,lon,address,images,status)
            VALUES (?,?,?,?,?,?,?,?,?,'pending')''',
            (report_id, user_id, description, category, severity, lat, lon, address, json.dumps(compressed_images))
        )
        if user_id:
            c.execute('UPDATE users SET reports_count=reports_count+1 WHERE id=?', (user_id,))
        conn.commit()
        conn.close()

        ai_score = verify_report_ai(description, category, severity)
        if ai_score >= 0.75:
            conn2 = sqlite3.connect(DB_FILE)
            c2 = conn2.cursor()
            c2.execute(
                "UPDATE reports SET verified=1, status='active', verified_by='auto_ai' WHERE id=?",
                (report_id,)
            )
            conn2.commit()
            conn2.close()

        return jsonify({
            "status": "success",
            "report_id": report_id,
            "message": "Reporte enviado. Será revisado en breve.",
            "verification_score": ai_score,
            "auto_verified": ai_score >= 0.75
        })

    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/api/reports/list', methods=['GET'])
def get_reports():
    try:
        verified_only = request.args.get('verified', 'true').lower() == 'true'
        category = request.args.get('category', None)
        days = int(request.args.get('days', 30))
        lat = request.args.get('lat', None)
        lon = request.args.get('lon', None)
        radius = float(request.args.get('radius', 50))

        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        cutoff = datetime.now() - timedelta(days=days)

        query = '''SELECT r.id,r.user_id,r.description,r.category,r.severity,
                          r.lat,r.lon,r.address,r.images,r.created_at,
                          r.verified,r.status,r.upvotes,r.downvotes,
                          u.name,u.photo
                   FROM reports r LEFT JOIN users u ON r.user_id=u.id
                   WHERE r.created_at > ?'''
        params = [cutoff]

        if verified_only:
            query += " AND r.verified=1"
        if category:
            query += " AND r.category=?"
            params.append(category)

        query += " ORDER BY r.created_at DESC LIMIT 200"
        c.execute(query, params)

        reports = []
        for row in c.fetchall():
            if lat and lon:
                dist = get_distance(float(lat), float(lon), row[5], row[6])
                if dist > radius:
                    continue
            reports.append({
                "id": row[0], "user_id": row[1], "description": row[2],
                "category": row[3], "severity": row[4],
                "lat": row[5], "lon": row[6], "address": row[7],
                "images": json.loads(row[8]) if row[8] else [],
                "created_at": row[9], "verified": bool(row[10]),
                "status": row[11], "upvotes": row[12], "downvotes": row[13],
                "user_name": row[14], "user_photo": row[15]
            })

        conn.close()
        return jsonify({"status": "success", "reports": reports, "total": len(reports)})

    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/api/reports/vote/<report_id>', methods=['POST'])
def vote_report(report_id):
    try:
        data = request.json
        user_id = data.get('user_id')
        vote_type = data.get('vote_type')

        if vote_type not in ['up', 'down']:
            return jsonify({"status": "error", "message": "Voto inválido"}), 400

        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute('SELECT vote_type FROM report_votes WHERE report_id=? AND user_id=?', (report_id, user_id))
        existing = c.fetchone()

        if existing:
            old_vote = existing[0]
            c.execute('UPDATE report_votes SET vote_type=? WHERE report_id=? AND user_id=?',
                      (vote_type, report_id, user_id))
            if old_vote == 'up':
                c.execute('UPDATE reports SET upvotes=upvotes-1 WHERE id=?', (report_id,))
            else:
                c.execute('UPDATE reports SET downvotes=downvotes-1 WHERE id=?', (report_id,))
        else:
            c.execute('INSERT INTO report_votes (report_id,user_id,vote_type) VALUES (?,?,?)',
                      (report_id, user_id, vote_type))

        if vote_type == 'up':
            c.execute('UPDATE reports SET upvotes=upvotes+1 WHERE id=?', (report_id,))
        else:
            c.execute('UPDATE reports SET downvotes=downvotes+1 WHERE id=?', (report_id,))

        conn.commit()
        c.execute('SELECT upvotes,downvotes FROM reports WHERE id=?', (report_id,))
        up, down = c.fetchone()
        conn.close()
        return jsonify({"status": "success", "upvotes": up, "downvotes": down})

    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/api/reports/heatmap', methods=['GET'])
def get_heatmap():
    try:
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute("SELECT lat, lon, upvotes FROM reports WHERE status != 'rejected'")
        reports = c.fetchall()
        conn.close()
        heatmap_data = [
            {"lat": r[0], "lon": r[1], "weight": min(1.0, 0.5 + (r[2] * 0.1))}
            for r in reports
        ]
        return jsonify(heatmap_data)
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/api/routes/calculate', methods=['POST'])
def calculate_route():
    try:
        data = request.json
        origin = data.get('origin', '').strip()
        destination = data.get('destination', '').strip()
        avoid_risks = data.get('avoid_risks', True)
        user_id = data.get('user_id')

        if not destination:
            return jsonify({"status": "error", "message": "Destino requerido"}), 400

        olat, olon = get_coordinates_db(origin)
        dlat, dlon = get_coordinates_db(destination)

        if not olat or not olon:
            olat, olon = 28.6353, -106.0886
        if not dlat or not dlon:
            return jsonify({"status": "error", "message": "Destino no encontrado"}), 400

        geometry = {"type": "LineString", "coordinates": [[olon, olat], [dlon, dlat]]}
        duration_min = get_distance(olat, olon, dlat, dlon) * 3
        distance_km = get_distance(olat, olon, dlat, dlon)

        try:
            url = f"http://router.project-osrm.org/route/v1/driving/{olon},{olat};{dlon},{dlat}"
            resp = __import__('requests').get(
                url,
                params={"overview": "full", "geometries": "geojson", "alternatives": "true"},
                timeout=8
            )
            if resp.status_code == 200:
                rd = resp.json()
                if rd.get('routes'):
                    best = None
                    best_risk = float('inf')
                    for route in rd['routes'][:3]:
                        rcoords = route['geometry']['coordinates']
                        rscore = 0
                        if avoid_risks:
                            for coord in rcoords[::max(1, len(rcoords) // 20)]:
                                lv = calculate_risk_at_point(coord[1], coord[0])
                                rscore += ZONE_RISK_SCORES.get(lv, 0)
                        if rscore < best_risk:
                            best_risk = rscore
                            best = route
                    if best:
                        geometry = best['geometry']
                        duration_min = best['duration'] / 60
                        distance_km = best['distance'] / 1000
        except Exception as osrm_e:
            print(f"OSRM unavailable: {osrm_e}")

        mid_lat = (olat + dlat) / 2
        mid_lon = (olon + dlon) / 2
        risk_level = calculate_risk_at_point(mid_lat, mid_lon)

        rf = {"verde": 1.0, "amarillo": 1.15, "rojo": 1.3, "negro": 1.5}
        factor = rf.get(risk_level, 1.0)

        transport_options = [
            {"mode": "Automóvil", "icon": "🚗", "time": f"{int(duration_min*factor)} min",
             "distance": f"{round(distance_km,1)} km", "risk": risk_level},
            {"mode": "Motocicleta", "icon": "🏍️", "time": f"{int(duration_min*0.85*factor)} min",
             "distance": f"{round(distance_km,1)} km", "risk": risk_level},
            {"mode": "Bicicleta", "icon": "🚴", "time": f"{int((distance_km/15)*60)} min",
             "distance": f"{round(distance_km,1)} km", "risk": "verde"},
            {"mode": "Caminando", "icon": "🚶", "time": f"{int((distance_km/5)*60)} min",
             "distance": f"{round(distance_km,1)} km", "risk": risk_level},
        ]

        warnings = []
        if risk_level in ["rojo", "negro"]:
            warnings.append({
                "type": "risk",
                "message": f"⚠️ Esta ruta atraviesa una zona de riesgo {risk_level.upper()}.",
                "severity": "CRITICAL"
            })
        elif risk_level == "amarillo":
            warnings.append({
                "type": "risk",
                "message": "🟡 Precaución: la ruta pasa por zonas de riesgo moderado.",
                "severity": "HIGH"
            })

        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute("SELECT type,description FROM natural_disasters WHERE active=1 AND expires_at>?", (datetime.now(),))
        for dtype, ddesc in c.fetchall():
            warnings.append({"type": "disaster", "message": f"⛔ {dtype.title()}: {ddesc}", "severity": "CRITICAL"})

        trip_id = None
        if user_id:
            trip_id = generate_id('trip_')
            c.execute(
                '''INSERT INTO trips (id,user_id,origin_name,dest_name,
                   origin_lat,origin_lon,dest_lat,dest_lon,
                   distance_km,duration_min,risk_level)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?)''',
                (trip_id, user_id, origin, destination,
                 olat, olon, dlat, dlon, round(distance_km, 2), int(duration_min), risk_level)
            )
            c.execute('UPDATE users SET trips_count=trips_count+1, total_km=total_km+? WHERE id=?',
                      (round(distance_km, 2), user_id))
        conn.commit()
        conn.close()

        return jsonify({
            "status": "success",
            "origin": {"lat": olat, "lon": olon, "name": origin},
            "destination": {"lat": dlat, "lon": dlon, "name": destination},
            "risk_level": risk_level,
            "risk_color": ZONE_COLORS.get(risk_level, "#10b981"),
            "distance_km": round(distance_km, 2),
            "duration_min": int(duration_min),
            "transport_options": transport_options,
            "route_geometry": geometry,
            "warnings": warnings,
            "trip_id": trip_id
        })

    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/api/routes/complete', methods=['POST'])
def complete_trip():
    try:
        data = request.json
        trip_id = data.get('trip_id')
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute("UPDATE trips SET status='completed', completed_at=? WHERE id=?", (datetime.now(), trip_id))
        conn.commit()
        conn.close()
        return jsonify({"status": "success", "message": "Viaje completado"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/api/geocode/reverse', methods=['POST'])
def reverse_geocode():
    try:
        data = request.json
        lat, lon = data.get('lat'), data.get('lon')
        if not lat or not lon:
            return jsonify({"status": "error", "message": "Coordenadas inválidas"}), 400

        address = "Chihuahua, Chih."
        if geolocator:
            try:
                loc = geolocator.reverse(f"{lat},{lon}", language='es', timeout=10)
                if loc:
                    addr = loc.raw.get('address', {})
                    parts = [addr.get('road', ''), addr.get('suburb', ''), addr.get('neighbourhood', '')]
                    address = ", ".join([p for p in parts if p]) or loc.address
            except:
                pass

        return jsonify({"status": "success", "address": address, "lat": lat, "lon": lon})

    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/api/disasters/list', methods=['GET'])
def get_disasters():
    try:
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute(
            '''SELECT id,type,lat,lon,radius_km,severity,description,created_at
               FROM natural_disasters WHERE active=1 AND (expires_at IS NULL OR expires_at > ?)
               ORDER BY created_at DESC''',
            (datetime.now(),)
        )
        disasters = [
            {"id": r[0], "type": r[1], "lat": r[2], "lon": r[3], "radius_km": r[4],
             "severity": r[5], "description": r[6], "created_at": r[7]}
            for r in c.fetchall()
        ]
        conn.close()
        return jsonify({"status": "success", "disasters": disasters})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/api/sos/trigger', methods=['POST'])
def trigger_sos():
    try:
        data = request.json
        user_id = data.get('user_id', 'anonymous')
        lat = data.get('lat')
        lon = data.get('lon')
        if user_id and lat and lon:
            conn = sqlite3.connect(DB_FILE)
            c = conn.cursor()
            c.execute(
                'INSERT INTO zone_history (user_id,zone_level,zone_name,lat,lon) VALUES (?,?,?,?,?)',
                (user_id, 'sos', 'SOS_ACTIVATED', lat, lon)
            )
            conn.commit()
            conn.close()
        return jsonify({"status": "success", "message": "SOS registrado"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/api/users/<user_id>/stats', methods=['GET'])
@app.route('/api/stats/user/<user_id>', methods=['GET'])
def get_user_stats(user_id):
    try:
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute(
            'SELECT name,photo,reports_count,rating,trips_count,total_km,created_at FROM users WHERE id=?',
            (user_id,)
        )
        u = c.fetchone()
        if not u:
            conn.close()
            return jsonify({"status": "error", "message": "Usuario no encontrado"}), 404

        c.execute(
            '''SELECT zone_level, COUNT(*) FROM zone_history
               WHERE user_id=? AND transited_at > ? GROUP BY zone_level''',
            (user_id, datetime.now() - timedelta(days=30))
        )
        monthly_zones = dict(c.fetchall())

        c.execute(
            '''SELECT zone_level, COUNT(*) FROM zone_history
               WHERE user_id=? AND transited_at > ? GROUP BY zone_level''',
            (user_id, datetime.now() - timedelta(days=365))
        )
        yearly_zones = dict(c.fetchall())

        c.execute('SELECT COUNT(*) FROM reports WHERE user_id=?', (user_id,))
        total_reports = c.fetchone()[0]

        total = sum(monthly_zones.values())
        safe_pct = round(monthly_zones.get('verde', 0) / total * 100) if total else 0

        conn.close()
        return jsonify({
            "status": "success",
            "user": {
                "name": u[0], "photo": u[1],
                "reports_count": u[2], "rating": u[3],
                "trips_count": u[4], "total_km": round(u[5] or 0, 1),
                "member_since": u[6]
            },
            "activity": {"reports": u[2]},
            "zone_history": {"safe_pct": safe_pct, "safe_streak": monthly_zones.get('verde', 0)},
            "zones_this_month": monthly_zones,
            "zones_this_year": yearly_zones,
            "total_reports": total_reports
        })

    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/api/admin/reports', methods=['GET'])
def get_pending_reports():
    try:
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute(
            '''SELECT r.id,r.description,r.category,r.severity,r.lat,r.lon,r.address,r.images,r.created_at,u.name
               FROM reports r LEFT JOIN users u ON r.user_id=u.id
               WHERE r.status='pending' ORDER BY r.created_at DESC LIMIT 50'''
        )
        reports = [
            {"id": r[0], "description": r[1], "category": r[2], "severity": r[3],
             "lat": r[4], "lon": r[5], "address": r[6],
             "images": json.loads(r[7]) if r[7] else [],
             "created_at": r[8], "user_name": r[9]}
            for r in c.fetchall()
        ]
        conn.close()
        return jsonify({"status": "success", "reports": reports})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/api/admin/reports/<report_id>', methods=['POST'])
def update_report_status(report_id):
    try:
        data = request.json
        action = data.get('action') or data.get('status')
        verified = 1 if action in ('approve', 'verified') else 0
        new_status = 'active' if action == 'approve' else ('rejected' if action == 'reject' else action)

        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute(
            "UPDATE reports SET status=?, verified=?, verified_by='admin', verified_at=? WHERE id=?",
            (new_status, verified, datetime.now(), report_id)
        )
        if action == 'approve':
            c.execute("SELECT lat,lon,severity FROM reports WHERE id=?", (report_id,))
            rep = c.fetchone()
            if rep:
                lv = 'rojo' if rep[2] == 'high' else 'amarillo'
                zid = generate_id('zone_auto_')
                exp = datetime.now() + timedelta(hours=24)
                c.execute(
                    '''INSERT INTO risk_zones
                    (id,name,lat,lon,radius_km,level,color,zone_type,description,expires_at,source)
                    VALUES (?,?,?,?,?,?,?,?,?,?,'admin_report')''',
                    (zid, f"Zona Temporal – reporte verificado", rep[0], rep[1],
                     0.5, lv, ZONE_COLORS[lv], 'reporte_verificado',
                     'Zona temporal por reporte verificado', exp)
                )
        conn.commit()
        conn.close()
        return jsonify({"status": "success", "action": action})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/api/places/safe-havens', methods=['GET'])
def get_safe_havens():
    try:
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute(
            "SELECT id,name,type,lat,lon,address FROM places WHERE LOWER(tags) LIKE '%gratuito%' OR type='Hospital' OR type='Emergencias'"
        )
        places = [
            {"id": r[0], "name": r[1], "category": r[2], "lat": r[3], "lon": r[4], "address": r[5]}
            for r in c.fetchall()
        ]
        conn.close()
        return jsonify(places)
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/api/health', methods=['GET'])
def health():
    try:
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM users")
        users = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM reports WHERE verified=1")
        reps = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM places")
        places = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM risk_zones WHERE active=1")
        zones = c.fetchone()[0]
        conn.close()
        return jsonify({
            "status": "healthy",
            "version": "2.1.0",
            "app": "Zeta – Navegación Segura Chihuahua",
            "database": "connected",
            "stats": {"users": users, "verified_reports": reps, "places": places, "active_zones": zones},
            "timestamp": datetime.now().isoformat()
        })
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    print(f"\n🛡️  ZETA PRO v2.1 — Puerto {port}")
    print(f"   http://localhost:{port}/api/health\n")
    app.run(host='0.0.0.0', port=port, debug=False)
