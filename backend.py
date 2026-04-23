import json, os, re, hashlib, math, sqlite3, base64
from datetime import datetime, timedelta
from flask import Flask, request, jsonify
from flask_cors import CORS

app = Flask(__name__)
CORS(app, resources={r"/api/*": {
    "origins": "*",
    "methods": ["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    "allow_headers": ["Content-Type", "Authorization", "X-Admin-Token"]
}})

DB_FILE       = 'zeta.db'
VERSION       = '2.2.0'
ADMIN_PIN     = os.environ.get('ADMIN_PIN', '9981')
ANTHROPIC_KEY = os.environ.get('ANTHROPIC_API_KEY', '')
ADMIN_TOKENS  = {}
os.makedirs('uploads/images', exist_ok=True)

try:
    from geopy.geocoders import Nominatim
    geolocator = Nominatim(user_agent="ZetaPro2_Chi", timeout=10)
    HAS_GEOPY = True
except:
    geolocator = None
    HAS_GEOPY = False

try:
    from PIL import Image
    HAS_PIL = True
except:
    HAS_PIL = False

try:
    import requests as req_lib
    HAS_REQUESTS = True
except:
    HAS_REQUESTS = False

def init_database():
    conn = sqlite3.connect(DB_FILE)
    c    = conn.cursor()
    c.executescript('''
    CREATE TABLE IF NOT EXISTS users (
        id TEXT PRIMARY KEY, email TEXT UNIQUE NOT NULL, name TEXT NOT NULL,
        photo TEXT, phone TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        last_login TIMESTAMP, reports_count INTEGER DEFAULT 0,
        verified INTEGER DEFAULT 0, rating REAL DEFAULT 5.0,
        total_km REAL DEFAULT 0, trips_count INTEGER DEFAULT 0,
        banned INTEGER DEFAULT 0,
        is_premium INTEGER DEFAULT 0,
        premium_until TIMESTAMP,
        language TEXT DEFAULT 'es',
        theme TEXT DEFAULT 'dark'
    );
    CREATE TABLE IF NOT EXISTS reports (
        id TEXT PRIMARY KEY, user_id TEXT, description TEXT NOT NULL,
        category TEXT NOT NULL, severity TEXT NOT NULL,
        lat REAL NOT NULL, lon REAL NOT NULL, address TEXT, images TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        verified INTEGER DEFAULT 0, verified_by TEXT, verified_at TIMESTAMP,
        status TEXT DEFAULT 'pending',
        upvotes INTEGER DEFAULT 0, downvotes INTEGER DEFAULT 0
    );
    CREATE TABLE IF NOT EXISTS places (
        id TEXT PRIMARY KEY, name TEXT NOT NULL, type TEXT NOT NULL,
        lat REAL NOT NULL, lon REAL NOT NULL,
        address TEXT, phone TEXT, website TEXT, description TEXT, images TEXT,
        rating REAL DEFAULT 0, total_reviews INTEGER DEFAULT 0,
        price_level INTEGER DEFAULT 2, hours TEXT, tags TEXT,
        city TEXT DEFAULT 'chihuahua',
        is_sponsored INTEGER DEFAULT 0,
        sponsor_until TIMESTAMP,
        sponsor_tier TEXT DEFAULT 'none',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS reviews (
        id TEXT PRIMARY KEY, place_id TEXT NOT NULL, user_id TEXT NOT NULL,
        rating INTEGER NOT NULL, comment TEXT, images TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        helpful_count INTEGER DEFAULT 0
    );
    CREATE TABLE IF NOT EXISTS risk_zones (
        id TEXT PRIMARY KEY, name TEXT NOT NULL,
        lat REAL NOT NULL, lon REAL NOT NULL, radius_km REAL NOT NULL,
        level TEXT NOT NULL, color TEXT NOT NULL, zone_type TEXT NOT NULL,
        active INTEGER DEFAULT 1, expires_at TIMESTAMP,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        source TEXT, description TEXT, incident_count INTEGER DEFAULT 1
    );
    CREATE TABLE IF NOT EXISTS zone_requests (
        id TEXT PRIMARY KEY, user_id TEXT,
        name TEXT NOT NULL, lat REAL NOT NULL, lon REAL NOT NULL,
        radius_km REAL DEFAULT 0.5, level TEXT NOT NULL,
        description TEXT, evidence_images TEXT,
        status TEXT DEFAULT 'pending',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        reviewed_by TEXT, reviewed_at TIMESTAMP, admin_note TEXT
    );
    CREATE TABLE IF NOT EXISTS report_votes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        report_id TEXT NOT NULL, user_id TEXT NOT NULL, vote_type TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(report_id, user_id)
    );
    CREATE TABLE IF NOT EXISTS zone_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id TEXT NOT NULL, zone_level TEXT NOT NULL, zone_name TEXT,
        lat REAL NOT NULL, lon REAL NOT NULL,
        transited_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS security_tips (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        tip_text TEXT NOT NULL, tip_category TEXT NOT NULL, icon TEXT NOT NULL,
        active INTEGER DEFAULT 1, priority INTEGER DEFAULT 1, zone_level TEXT
    );
    CREATE TABLE IF NOT EXISTS trips (
        id TEXT PRIMARY KEY, user_id TEXT,
        origin_name TEXT, dest_name TEXT,
        origin_lat REAL, origin_lon REAL,
        dest_lat REAL, dest_lon REAL,
        distance_km REAL, duration_min INTEGER, risk_level TEXT,
        started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        completed_at TIMESTAMP, status TEXT DEFAULT 'active'
    );
    CREATE TABLE IF NOT EXISTS ads (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL, body TEXT NOT NULL,
        cta TEXT, url TEXT, icon TEXT DEFAULT '📍',
        sponsor_name TEXT NOT NULL,
        category TEXT DEFAULT 'general',
        city TEXT DEFAULT 'both',
        active INTEGER DEFAULT 1,
        impressions INTEGER DEFAULT 0,
        clicks INTEGER DEFAULT 0,
        priority INTEGER DEFAULT 1,
        ends_at TIMESTAMP,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS ai_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id TEXT, role TEXT NOT NULL,
        content TEXT NOT NULL, tokens INTEGER DEFAULT 0,
        action TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS notifications (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id TEXT, title TEXT NOT NULL, body TEXT NOT NULL,
        icon TEXT DEFAULT '🔔', color TEXT DEFAULT '#00d4ff',
        read_at TIMESTAMP, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        broadcast INTEGER DEFAULT 0
    );
    ''')
    
    migrations = [
        ("users",  "is_premium INTEGER DEFAULT 0"),
        ("users",  "premium_until TIMESTAMP"),
        ("users",  "language TEXT DEFAULT 'es'"),
        ("users",  "theme TEXT DEFAULT 'dark'"),
        ("places", "city TEXT DEFAULT 'chihuahua'"),
        ("places", "is_sponsored INTEGER DEFAULT 0"),
        ("places", "sponsor_until TIMESTAMP"),
        ("places", "sponsor_tier TEXT DEFAULT 'none'"),
    ]
    for table, col_def in migrations:
        try:
            c.execute(f"ALTER TABLE {table} ADD COLUMN {col_def}")
        except:
            pass

    conn.commit()
    conn.close()

init_database()

def generate_id(prefix=''):
    ts  = str(int(datetime.now().timestamp() * 1000))
    rnd = hashlib.md5(os.urandom(16)).hexdigest()[:8]
    return f"{prefix}{ts}_{rnd}"

def get_distance(lat1, lon1, lat2, lon2):
    R = 6371
    dLat = math.radians(lat2 - lat1)
    dLon = math.radians(lon2 - lon1)
    a = (math.sin(dLat/2)**2
         + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2))
         * math.sin(dLon/2)**2)
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

def compress_image(b64, sz=(800, 800), q=82):
    if not HAS_PIL or not b64 or 'base64,' not in b64:
        return b64
    try:
        from io import BytesIO
        hdr, data = b64.split(',', 1)
        img = Image.open(BytesIO(base64.b64decode(data)))
        if img.mode in ('RGBA', 'P'):
            img = img.convert('RGB')
        img.thumbnail(sz, Image.Resampling.LANCZOS)
        out = BytesIO()
        img.save(out, format='JPEG', quality=q, optimize=True)
        return 'data:image/jpeg;base64,' + base64.b64encode(out.getvalue()).decode()
    except:
        return b64

ZONE_COLORS = {
    "negro":    "#1a1a1a",
    "rojo":     "#dc2626",
    "amarillo": "#f59e0b",
    "verde":    "#10b981"
}
ZONE_SCORES = {"negro": 4, "rojo": 3, "amarillo": 2, "verde": 0}

def risk_at(lat, lon):
    conn = sqlite3.connect(DB_FILE); c = conn.cursor()
    c.execute("SELECT lat,lon,radius_km,level FROM risk_zones "
              "WHERE active=1 AND (expires_at IS NULL OR expires_at>?)",
              (datetime.now(),))
    best = "verde"; bs = 0
    for zl, zo, r, lv in c.fetchall():
        if get_distance(lat, lon, zl, zo) <= r:
            s = ZONE_SCORES.get(lv, 0)
            if s > bs: bs = s; best = lv
    conn.close()
    return best

def zone_name_at(lat, lon):
    conn = sqlite3.connect(DB_FILE); c = conn.cursor()
    c.execute("SELECT name,level,lat,lon,radius_km FROM risk_zones "
              "WHERE active=1 ORDER BY radius_km ASC")
    for nm, lv, zl, zo, r in c.fetchall():
        if get_distance(lat, lon, zl, zo) <= r:
            conn.close(); return nm, lv
    conn.close(); return None, None

def admin_ok(req):
    tok = (req.headers.get('X-Admin-Token', '')
           or (req.json or {}).get('token', ''))
    return tok in ADMIN_TOKENS and ADMIN_TOKENS[tok] > datetime.now()

def get_coords_free(location_name):
    """Geocodifica cualquier dirección usando Nominatim (gratis, sin API key)."""
    if not location_name:
        return None, None
    # Si ya son coordenadas
    if ',' in location_name:
        try:
            p = location_name.split(',')
            la, lo = float(p[0].strip()), float(p[1].strip())
            if 20.0 <= la <= 33.0 and -118.0 <= lo <= -86.0:
                return la, lo
        except:
            pass
    # Buscar en lugares propios
    conn = sqlite3.connect(DB_FILE); c = conn.cursor()
    c.execute('SELECT lat,lon FROM places WHERE LOWER(name) LIKE ? LIMIT 1',
              (f'%{location_name.lower()}%',))
    row = c.fetchone(); conn.close()
    if row: return row[0], row[1]
    # Nominatim via requests
    if HAS_REQUESTS:
        try:
            resp = req_lib.get('https://nominatim.openstreetmap.org/search',
                params={'q': location_name + ', México', 'format': 'json',
                        'limit': 1, 'accept-language': 'es', 'countrycodes': 'mx'},
                headers={'User-Agent': 'ZetaPro/2.2'}, timeout=7)
            results = resp.json()
            if results:
                return float(results[0]['lat']), float(results[0]['lon'])
        except:
            pass
    # Fallback: geopy
    if geolocator:
        try:
            r = geolocator.geocode(location_name + ', México', timeout=8)
            if r: return r.latitude, r.longitude
        except:
            pass
    return None, None

def seed_tips():
    conn = sqlite3.connect(DB_FILE); c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM security_tips")
    if c.fetchone()[0] > 0: conn.close(); return
    tips = [
        ("Evita zonas NEGRO después de las 10pm.",           "zona_negro",    "⚫"),
        ("En zona ROJA no te detengas. Sigue circulando.",   "zona_rojo",     "🔴"),
        ("Zona AMARILLA: ventanas subidas y seguros.",        "zona_amarillo", "🟡"),
        ("Zonas VERDES son tu mejor ruta.",                   "zona_verde",    "🟢"),
        ("Comparte tu ruta con un familiar.",                 "general",       "📍"),
        ("Mantén el teléfono cargado al salir de noche.",     "general",       "🔋"),
        ("Usa rutas iluminadas aunque sean más largas.",      "general",       "💡"),
        ("Emergencias: marca 911 sin saldo.",                 "emergencia",    "🚨"),
        ("Cruz Roja Chihuahua: 614-415-4545 — 24 hrs.",      "emergencia",    "🏥"),
        ("Cruz Roja Juárez: 656-415-4545 — 24 hrs.",         "emergencia",    "🏥"),
        ("Bomberos Chihuahua: 614-410-0073.",                 "emergencia",    "🚒"),
        ("Denuncia anónima: Línea 089 — sin costo.",          "emergencia",    "📱"),
        ("Policía Municipal Chihuahua: 614-200-9000.",        "emergencia",    "👮"),
        ("Policía Municipal Juárez: 656-688-2000.",           "emergencia",    "👮"),
        ("Varía tu ruta para no ser predecible.",             "general",       "🔄"),
        ("No dejes objetos visibles en el tablero.",          "vehiculo",      "🎒"),
        ("Estaciona en zonas bien iluminadas.",               "vehiculo",      "🅿️"),
        ("Mantén el tanque con al menos 1/4 de combustible.", "vehiculo",      "⛽"),
        ("Guarda el celular en zonas de riesgo.",             "peatonal",      "📵"),
        ("Reporta incidentes con foto y GPS.",                "general",       "📷"),
        ("De noche, prefiere las avenidas principales.",      "nocturno",      "🌙"),
        ("Evita callejones sin alumbrado.",                   "nocturno",      "🚫"),
        ("Star Médica Chihuahua: 614-439-9000.",              "emergencia",    "🏨"),
        ("Star Médica Juárez: 656-628-0000.",                 "emergencia",    "🏨"),
        ("Ministerio Público Chihuahua: 614-200-0070.",       "emergencia",    "⚖️"),
    ]
    for tip in tips:
        c.execute("INSERT INTO security_tips (tip_text,tip_category,icon) VALUES (?,?,?)", tip)
    conn.commit(); conn.close()

def seed_places():
    conn = sqlite3.connect(DB_FILE); c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM places")
    if c.fetchone()[0] > 0: conn.close(); return

    places = [
        # ── CHIHUAHUA ──────────────────────────────────────────
        ("p001","Catedral Metropolitana","Templo/Cultura",28.6358,-106.0773,"Plaza de Armas S/N","+52 614 410 3858","Catedral barroca siglo XVIII.",4.8,2847,1,"Lun-Dom 7:00-20:00","cultura,historia","chihuahua"),
        ("p002","Quinta Gameros – Museo","Museo",28.6400,-106.0850,"Paseo Bolívar 401","+52 614 416 6684","Mansión art nouveau de 1910.",4.7,1923,1,"Mar-Dom 9:00-17:00","museo,arte","chihuahua"),
        ("p003","Casa Pancho Villa","Museo",28.6320,-106.0910,"Calle 10a No. 3010","+52 614 416 2958","Casa donde vivió Pancho Villa.",4.6,1542,1,"Mar-Dom 9:00-18:00","museo,revolución","chihuahua"),
        ("p004","Palacio de Gobierno","Monumento",28.6355,-106.0768,"Plaza Hidalgo S/N","","Murales de Aarón Piña Mora.",4.6,1234,1,"Lun-Dom 8:00-18:00","gobierno,murales","chihuahua"),
        ("p005","Plaza de Armas","Plaza",28.6357,-106.0772,"Av. Independencia y Guerrero","","Plaza principal de Chihuahua.",4.7,5432,1,"24 horas","plaza,centro","chihuahua"),
        ("p006","Acueducto Colonial","Monumento",28.6280,-106.0710,"Av. Zarco, Santa Rosa","","Acueducto siglo XVIII.",4.6,1567,1,"24 horas","acueducto,colonial","chihuahua"),
        ("p007","Teatro de los Héroes","Teatro",28.6382,-106.0862,"Av. Ocampo y Colón","+52 614 415 3236","Principal teatro, 1200 personas.",4.7,1087,2,"Según prog.","teatro,cultura","chihuahua"),
        ("p008","Museo del Desierto / Mamut","Museo",28.6280,-106.0795,"Av. Universidad 2903","+52 614 439 3900","Museo paleontológico.",4.5,987,1,"Mar-Dom 10:00-18:00","museo,paleontología","chihuahua"),
        ("p009","Burritos Cano","Taquería",28.6360,-106.0910,"Calle 21 No. 2015","+52 614 416 0303","Los mejores burritos desde 1952.",4.8,4521,1,"Lun-Sáb 7:00-15:00","burritos,machaca","chihuahua"),
        ("p010","Tacos El Cuñado","Taquería",28.6410,-106.0970,"Av. División del Norte 3200","+52 614 414 2255","Carne asada artesanal.",4.7,3421,1,"Lun-Dom 8:00-18:00","tacos,carne asada","chihuahua"),
        ("p011","La Calesa","Restaurante",28.6348,-106.0882,"Av. Juárez 3300","+52 614 410 2828","Cocina tradicional chihuahuense.",4.6,2341,2,"Lun-Dom 7:30-22:00","mexicano,machaca","chihuahua"),
        ("p012","Gorditas Doña Lily","Comida Típica",28.6372,-106.0870,"Mercado Central","+52 614 410 0900","Gorditas de harina artesanales.",4.6,2109,1,"Lun-Dom 7:00-16:00","gorditas,típico","chihuahua"),
        ("p013","Café Río Grande","Cafetería",28.6370,-106.0855,"Paseo Bolívar 1100","+52 614 416 1222","Café de la Sierra Tarahumara.",4.6,1876,2,"Lun-Dom 7:00-21:00","café,brunch","chihuahua"),
        ("p014","Xocoveza Café & Chocolate","Cafetería",28.6406,-106.0870,"Calle 28 No. 2200","+52 614 415 6600","Chocolates artesanales.",4.7,987,2,"Lun-Sáb 8:00-21:00","café,chocolate","chihuahua"),
        ("p015","Starbucks Plaza de Armas","Cafetería",28.6356,-106.0771,"Av. Aldama y Plaza de Armas","+52 614 415 7700","Vista a la Catedral.",4.3,3456,3,"Lun-Dom 6:30-22:00","café,wifi","chihuahua"),
        ("p016","Mariscos Altamira","Marisquería",28.6440,-106.0985,"Av. Heroico Colegio Militar 3800","+52 614 414 5678","Camarones al mojo y ceviche.",4.6,2134,3,"Lun-Dom 11:00-20:00","mariscos,ceviche","chihuahua"),
        ("p017","El Rey de la Arrachera","Restaurante",28.6480,-106.1000,"Blvd. Ortiz Mena 4500","+52 614 412 3456","Arrachera al carbón.",4.6,1987,3,"Lun-Dom 13:00-23:00","arrachera,carbón","chihuahua"),
        ("p018","Black Angus Steakhouse","Restaurante",28.6520,-106.1100,"Periférico R. Almada km 5.5","+52 614 411 7700","Cortes Black Angus premium.",4.7,1456,4,"Lun-Dom 13:00-23:00","cortes,fine dining","chihuahua"),
        ("p019","Burnout's Burger","Hamburguesas",28.6445,-106.0980,"Av. División del Norte 4500","+52 614 414 7700","Hamburguesas 100% Angus.",4.6,2897,2,"Lun-Dom 12:00-23:00","hamburguesas,gourmet","chihuahua"),
        ("p020","Sushi Nori","Restaurante Japonés",28.6530,-106.1080,"Blvd. Ortiz Mena 6200","+52 614 411 8800","Sushi premium.",4.5,1245,3,"Lun-Dom 13:00-23:00","sushi,japonés","chihuahua"),
        ("p021","Pizza Bona","Pizzería",28.6460,-106.0995,"Av. Universidad 4000","+52 614 413 9900","Pizza al horno de leña.",4.4,3210,2,"Lun-Dom 12:00-23:00","pizza,leña","chihuahua"),
        ("p022","Las 100 Tortillas","Comida Típica",28.6388,-106.0892,"Calle 10 No. 2700","+52 614 416 9900","Tortillas de harina artesanales.",4.8,3456,1,"Lun-Sáb 6:00-14:00","tortillas,artesanal","chihuahua"),
        ("p023","Fashion Mall Chihuahua","Centro Comercial",28.6580,-106.1170,"Blvd. Teófilo Borunda 8401","+52 614 418 7000","El más moderno de Chihuahua.",4.5,8923,3,"Lun-Dom 10:00-21:00","compras,cine","chihuahua"),
        ("p024","Plaza Sendero Chihuahua","Centro Comercial",28.6610,-106.1220,"Blvd. Teófilo Borunda 9200","+52 614 418 9900","Cinépolis, HEB y más.",4.6,6543,3,"Lun-Dom 10:00-22:00","compras,HEB","chihuahua"),
        ("p025","Galerías Chihuahua","Centro Comercial",28.6490,-106.1090,"Blvd. Ortiz Mena 6200","+52 614 411 9000","Mall familiar.",4.3,5671,2,"Lun-Dom 10:00-21:00","compras,cine","chihuahua"),
        ("p026","Parque El Rejón","Parque",28.6150,-106.1150,"Av. El Palmar","","Lago y pista para correr.",4.4,3456,1,"Lun-Dom 6:00-22:00","parque,gratuito","chihuahua"),
        ("p027","Bosque Urbano Chihuahua","Parque",28.6560,-106.1200,"Periférico de la Juventud","","Pulmón verde de Chihuahua.",4.6,4123,1,"Lun-Dom 5:00-22:00","parque,ciclismo","chihuahua"),
        ("p028","Parque Franklin","Parque",28.6490,-106.1030,"Blvd. Francisco Villa","","Skatepark y canchas.",4.5,2109,1,"Lun-Dom 6:00-22:00","parque,deportes","chihuahua"),
        ("p029","Cinépolis Sendero","Cine",28.6615,-106.1225,"Plaza Sendero","+52 800 832 4600","4DX y VIP.",4.5,6789,3,"Lun-Dom 11:00-23:30","cine,4DX","chihuahua"),
        ("p030","Holiday Inn Chihuahua","Hotel",28.6380,-106.0900,"Escudero 702","+52 614 414 3350","4 estrellas, alberca.",4.5,2123,3,"24 hrs","hotel,4 estrellas","chihuahua"),
        ("p031","Hyatt Place Chihuahua","Hotel",28.6510,-106.1120,"Blvd. Ortiz Mena 3700","+52 614 442 1234","Rooftop, spa y alberca.",4.7,1456,4,"24 hrs","hotel,lujo","chihuahua"),
        ("p032","Hospital Central del Estado","Hospital",28.6560,-106.0950,"Calle Teófilo Borunda 1370","+52 614 414 2233","Principal hospital público.",3.8,2341,1,"24 hrs","hospital,urgencias","chihuahua"),
        ("p033","Star Médica Chihuahua","Hospital",28.6490,-106.1050,"Av. Heroico Colegio Militar 4430","+52 614 439 9000","Hospital privado 24 hrs.",4.5,1987,4,"24 hrs","hospital,privado","chihuahua"),
        ("p034","Cruz Roja Chihuahua","Emergencias",28.6430,-106.0890,"Calle Homero 2019","+52 614 415 4545","Ambulancias 24 hrs.",4.7,1234,1,"24 hrs","emergencias,ambulancia","chihuahua"),
        ("p035","UACH Campus Central","Universidad",28.6350,-106.0890,"Escorza 900","+52 614 439 1500","Universidad Autónoma de Chihuahua.",4.4,5678,1,"Lun-Vie 7:00-21:00","universidad,pública","chihuahua"),
        ("p036","Tec de Monterrey Chihuahua","Universidad",28.6650,-106.1100,"Av. Heroico Colegio Militar 4700","+52 614 442 2000","Campus Tec.",4.5,2876,4,"Lun-Vie 7:00-22:00","universidad,privada","chihuahua"),
        ("p037","HEB Chihuahua Norte","Supermercado",28.6618,-106.1228,"Plaza Sendero","+52 614 418 9999","Farmacia y panadería.",4.5,7890,2,"Lun-Dom 6:00-24:00","supermercado,HEB","chihuahua"),
        ("p038","Walmart Chihuahua","Supermercado",28.6280,-106.0720,"Av. División del Norte 2000","+52 614 416 0800","El más céntrico.",4.1,9876,2,"Lun-Dom 7:00-23:00","supermercado,walmart","chihuahua"),
        ("p039","Aeropuerto Roberto Fierro","Transporte",28.7029,-105.9645,"Carretera Chihuahua-Juárez km 20","+52 614 420 0015","Vuelos nac. e intl.",4.2,4567,2,"4:00-23:00","aeropuerto","chihuahua"),
        ("p040","Templo de San Francisco","Templo",28.6340,-106.0785,"Calle Victoria y Guerrero","+52 614 415 2020","Templo franciscano 1721.",4.5,876,1,"Lun-Dom 7:00-20:00","iglesia,colonial","chihuahua"),
        ("p041","Smart Fit Chihuahua","Gimnasio",28.6540,-106.1150,"Blvd. Borunda 8000","+52 800 090 3030","Gym 24 hrs.",4.3,3456,2,"24 hrs","gimnasio","chihuahua"),
        ("p042","Restaurante Tarahumara","Restaurante",28.6345,-106.0885,"Calle Aldama 1800","+52 614 415 8800","Gastronomía rarámuri.",4.5,1234,2,"Lun-Sáb 9:00-21:00","tarahumara,regional","chihuahua"),
        ("p043","Zona Dorada – Bares","Entretenimiento",28.6430,-106.0990,"Av. División del Norte","","Bares y vida nocturna.",4.2,8901,3,"Jue-Dom 20:00-04:00","bares,nocturno","chihuahua"),
        ("p044","La Noria Restaurante Bar","Restaurante",28.6350,-106.0800,"Aldama 407","+52 614 410 1616","Cocina de autor local.",4.6,1234,3,"Lun-Dom 13:00-23:00","cocina de autor,bar","chihuahua"),
        ("p045","VIPS Chihuahua","Restaurante",28.6365,-106.0865,"Av. Juárez y V. Guerrero","+52 614 415 3300","Variedad mexicana 24 hrs.",4.2,2134,2,"24 hrs","24hrs,familiar","chihuahua"),
        # ── CIUDAD JUÁREZ ──────────────────────────────────────
        ("j001","MUREF – Museo Revolución","Museo",31.7393,-106.4896,"Av. 16 de Septiembre 3000","+52 656 688 3883","Museo de la Revolución en la Frontera.",4.7,1456,1,"Mar-Dom 10:00-18:00","museo,revolución","juarez"),
        ("j002","Museo de Arte Juárez (MACJ)","Museo",31.7350,-106.4900,"Av. de las Américas 2","+52 656 688 3525","Arte contemporáneo fronterizo.",4.5,876,1,"Mar-Dom 10:00-18:00","museo,arte","juarez"),
        ("j003","Monumento a Benito Juárez","Monumento",31.7383,-106.4874,"Av. 16 de Septiembre y Lincoln","","Monumento icónico.",4.4,2341,1,"24 horas","monumento,historia","juarez"),
        ("j004","Plaza de Armas Juárez","Plaza",31.7380,-106.4870,"Centro Histórico Juárez","","Plaza principal con Catedral.",4.5,3210,1,"24 horas","plaza,centro","juarez"),
        ("j005","Catedral Metropolitana Juárez","Templo",31.7381,-106.4873,"Av. Lerdo y 16 de Septiembre","+52 656 612 0612","Catedral siglo XIX.",4.6,1987,1,"Lun-Dom 7:00-20:00","catedral,colonial","juarez"),
        ("j006","Misión de Guadalupe","Templo",31.7375,-106.4878,"Guadalupe y Mariscal","+52 656 612 1084","Misión siglo XVII.",4.7,1123,1,"Lun-Dom 8:00-19:00","misión,histórico","juarez"),
        ("j007","Puente Internacional Santa Fe","Monumento",31.7432,-106.4854,"Av. Lerdo y Frontera","","Puente México-EUA.",4.3,5678,1,"24 horas","frontera,puente","juarez"),
        ("j008","Zona PRONAF","Entretenimiento",31.7180,-106.4720,"Av. de las Torres","","Zona gastronómica y cultural.",4.4,4321,3,"Lun-Dom 10:00-22:00","gastronomía,turismo","juarez"),
        ("j009","Parque El Chamizal","Parque",31.7530,-106.4970,"Av. del Chamizal","","Parque histórico a orillas del Río Bravo.",4.5,3456,1,"Lun-Dom 6:00-21:00","parque,gratuito","juarez"),
        ("j010","Parque Central Bermúdez","Parque",31.6920,-106.4200,"Calzada Bermúdez","","Lago y ciclopista.",4.4,2109,1,"Lun-Dom 6:00-21:00","parque,deportes","juarez"),
        ("j011","Mercado Cuauhtémoc","Mercado",31.7370,-106.4860,"Av. Cuauhtémoc y Ugarte","","Artesanías y comida local.",4.3,1876,1,"Lun-Dom 8:00-20:00","mercado,artesanías","juarez"),
        ("j012","Burritos El Tecolote","Taquería",31.7201,-106.4508,"Plutarco Elías Calles 2901","+52 656 629 0123","Institución local desde 1969.",4.8,6789,1,"Lun-Sáb 7:00-16:00","burritos,machaca","juarez"),
        ("j013","La Fogata de Juárez","Restaurante",31.6918,-106.4216,"Av. Tecnológico y Paseo Triunfo","+52 656 648 7890","Cortes al carbón.",4.6,2341,3,"Lun-Dom 13:00-23:00","cortes,carbón","juarez"),
        ("j014","El Norteño Tacos","Taquería",31.7250,-106.4650,"Av. López Mateos 2100","+52 656 613 4567","Favorito local.",4.7,3456,1,"Lun-Dom 8:00-18:00","tacos,carne asada","juarez"),
        ("j015","Kentucky Club (Bar Histórico)","Restaurante",31.7371,-106.4877,"Av. Juárez 629","+52 656 612 1161","Bar fundado en 1920. Cuna del margarita.",4.5,4567,3,"Lun-Dom 12:00-02:00","bar,histórico","juarez"),
        ("j016","Machakos Kitchen","Taquería",31.7160,-106.4430,"Av. Paseo Triunfo 3010","+52 656 648 3210","Machaca estilo Juárez.",4.7,2890,1,"Lun-Dom 7:00-17:00","machaca,burritos","juarez"),
        ("j017","La Fogata Grill Juárez","Restaurante",31.6895,-106.4178,"Blvd. Zaragoza 12001","+52 656 627 5500","Parrillada y cortes.",4.6,1987,3,"Lun-Dom 13:00-23:00","parrilla,cortes","juarez"),
        ("j018","El Mesón del Caballo","Restaurante",31.7050,-106.4350,"Blvd. Tomás Fernández 7500","+52 656 640 1234","Carnes al carbón.",4.4,1567,2,"Lun-Dom 12:00-22:00","carnes,norteño","juarez"),
        ("j019","Tacos de Canasta El Güero","Taquería",31.7420,-106.4800,"Av. Tecnológico 2800","+52 656 613 7890","Tacos de canasta tradicionales.",4.5,1234,1,"Lun-Sáb 8:00-15:00","tacos,desayuno","juarez"),
        ("j020","Starbucks Galerías Tec","Cafetería",31.6980,-106.4300,"Galerías Tec, Av. Tecnológico","","Café con wifi.",4.3,2345,3,"Lun-Dom 6:30-22:00","café,wifi","juarez"),
        ("j021","Mariscos El Barquito","Marisquería",31.7280,-106.4620,"Av. Valentín Fuentes 1800","+52 656 614 2345","Ceviche y aguachile fresco.",4.6,1876,2,"Lun-Dom 11:00-20:00","mariscos,ceviche","juarez"),
        ("j022","Galerías Tecnológico","Centro Comercial",31.6975,-106.4295,"Av. Tecnológico 3000","+52 656 648 8800","Mall más moderno de Juárez.",4.6,9876,3,"Lun-Dom 10:00-22:00","compras,cine","juarez"),
        ("j023","Plaza Las Misiones","Centro Comercial",31.6830,-106.4050,"Blvd. Zaragoza 14000","+52 656 627 3000","Walmart y Cinépolis.",4.4,6543,2,"Lun-Dom 10:00-21:00","compras,walmart","juarez"),
        ("j024","Mall de las Aves","Centro Comercial",31.7420,-106.4220,"Av. Manuel J. Clouthier 2050","+52 656 617 9000","Liverpool y restaurantes.",4.3,5432,3,"Lun-Dom 10:00-21:00","compras,liverpool","juarez"),
        ("j025","Walmart Supercenter Juárez","Supermercado",31.7020,-106.4280,"Blvd. Zaragoza 10000","+52 656 629 0100","Supermercado completo.",4.1,8765,2,"Lun-Dom 7:00-23:00","supermercado,walmart","juarez"),
        ("j026","HEB Ciudad Juárez","Supermercado",31.6900,-106.4150,"Av. Tecnológico 8500","+52 656 648 7700","HEB con farmacia.",4.5,5678,2,"Lun-Dom 6:00-24:00","supermercado,HEB","juarez"),
        ("j027","Hotel Camino Real Juárez","Hotel",31.7175,-106.4695,"Av. Lincoln y Palmas","+52 656 227 9000","Hotel lujo en PRONAF.",4.6,2134,4,"24 hrs","hotel,lujo","juarez"),
        ("j028","Hilton Garden Inn Juárez","Hotel",31.6950,-106.4260,"Blvd. Díaz Ordaz y Gómez Morín","+52 656 228 0100","Hotel ejecutivo.",4.5,1456,3,"24 hrs","hotel,ejecutivo","juarez"),
        ("j029","Hotel Lucerna Juárez","Hotel",31.7190,-106.4700,"Av. Paseo de la Victoria 3976","+52 656 629 9900","Hotel clásico desde 1975.",4.4,1987,3,"24 hrs","hotel,clásico","juarez"),
        ("j030","Fiesta Inn Juárez","Hotel",31.6920,-106.4230,"Blvd. Tomás Fernández 8281","+52 656 207 7000","Hotel moderno.",4.4,1234,3,"24 hrs","hotel,moderno","juarez"),
        ("j031","Hospital General Juárez","Hospital",31.7350,-106.4700,"Av. 16 de Septiembre y Tlaxcala","+52 656 615 0000","Principal hospital público.",3.9,2341,1,"24 hrs","hospital,urgencias","juarez"),
        ("j032","Hospital Star Médica Juárez","Hospital",31.6940,-106.4230,"Av. Tecnológico y Circunvalación","+52 656 628 0000","Hospital privado.",4.5,1456,4,"24 hrs","hospital,privado","juarez"),
        ("j033","Cruz Roja Juárez","Emergencias",31.7300,-106.4850,"Av. 16 de Septiembre 4400","+52 656 415 4545","Cruz Roja 24 hrs.",4.6,987,1,"24 hrs","emergencias,ambulancia","juarez"),
        ("j034","IMSS Clínica 66 Juárez","Hospital",31.6970,-106.4310,"Av. Tecnológico y Hermanos Escobar","+52 800 623 2323","Clínica IMSS.",3.7,3456,1,"24 hrs","hospital,IMSS","juarez"),
        ("j035","UACJ – Campus Central","Universidad",31.7260,-106.4830,"Av. Plutarco Elías Calles 1210","+52 656 688 2100","Universidad Autónoma de Juárez.",4.4,4567,1,"Lun-Vie 7:00-21:00","universidad,pública","juarez"),
        ("j036","Tec de Monterrey Juárez","Universidad",31.6895,-106.4170,"Av. Henry Dunant 1000","+52 656 629 8900","Campus Tec.",4.5,2345,4,"Lun-Vie 7:00-22:00","universidad,privada","juarez"),
        ("j037","Cinépolis Galerías Tec","Cine",31.6972,-106.4298,"Galerías Tecnológico","+52 800 832 4600","4DX y VIP.",4.5,5432,3,"Lun-Dom 11:00-23:30","cine,4DX","juarez"),
        ("j038","Estadio Olímpico Benito Juárez","Estadio",31.7210,-106.4580,"Av. Universidad y Carlos Amaya","+52 656 614 9000","Estadio FC Juárez.",4.4,3456,2,"Según eventos","estadio,fútbol","juarez"),
        ("j039","Aeropuerto Internacional Juárez","Transporte",31.6363,-106.4287,"Carretera Panamericana km 11","+52 656 775 3000","Vuelos a CDMX, Houston y más.",4.2,6789,2,"4:00-23:00","aeropuerto","juarez"),
        ("j040","Central de Autobuses Juárez","Transporte",31.7295,-106.4790,"Blvd. Oscar Flores 4702","+52 656 617 8888","Rutas a CDMX, Chihuahua.",3.9,2345,2,"24 horas","autobuses,terminal","juarez"),
        ("j041","Smart Fit Juárez","Gimnasio",31.6990,-106.4280,"Galerías Tec","+52 800 090 3030","Gym 24 hrs.",4.3,2134,2,"24 hrs","gimnasio","juarez"),
        ("j042","Zona Rosa de Juárez","Entretenimiento",31.7350,-106.4890,"Av. Juárez, Centro","","Bares y vida nocturna.",3.9,4321,3,"Vie-Dom 20:00-04:00","bares,nocturno","juarez"),
        ("j043","Parque Extremo Juárez","Entretenimiento",31.6850,-106.4080,"Blvd. Zaragoza 10501","","Escalada, zip-line.",4.3,1234,3,"Lun-Dom 10:00-21:00","extremo,aventura","juarez"),
    ]

    for p in places:
        pid,name,ptype,lat,lon,addr,phone,desc,rating,reviews,price,hours,tags,city = p
        c.execute(
            'INSERT OR IGNORE INTO places '
            '(id,name,type,lat,lon,address,phone,description,'
            'rating,total_reviews,price_level,hours,tags,city) '
            'VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
            (pid,name,ptype,lat,lon,addr,phone,desc,rating,reviews,price,hours,tags,city))

    conn.commit(); conn.close()
    print(f"✅ {len(places)} lugares cargados")

def seed_zones():
    conn = sqlite3.connect(DB_FILE); c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM risk_zones")
    if c.fetchone()[0] > 0: conn.close(); return
    ZC = ZONE_COLORS
    zones = [
        ("z001","Alta Violencia – Col. Obrera",28.620,-106.088,1.2,"negro","homicidio","Alta peligrosidad."),
        ("z002","Riesgo – Blvd. Juan Pablo II Sur",28.610,-106.075,1.0,"negro","robo_violento","Robos armados nocturnos."),
        ("z003","Peligrosidad – Col. Cerro Grande",28.598,-106.062,1.5,"negro","homicidio","Zona de alta peligrosidad."),
        ("z004","Alerta – Col. Las Granjas",28.648,-106.040,1.0,"rojo","robo","Robos a negocios."),
        ("z005","Precaución – Centro Nocturno",28.636,-106.080,0.8,"rojo","asalto","Asaltos nocturnos."),
        ("z006","Atención – Mercado Central",28.637,-106.087,0.5,"amarillo","robo_menor","Robos menores."),
        ("z007","Moderado – Zona Camiones",28.648,-106.079,0.7,"amarillo","estafa","Taxistas no autorizados."),
        ("z008","Zona Segura – Campestre Norte",28.660,-106.120,1.5,"verde","zona_segura","Colonia residencial."),
        ("z009","Zona Segura – Fashion Mall",28.658,-106.117,1.0,"verde","zona_segura","Vigilancia privada."),
        ("z010","Zona Segura – Centro Diurno",28.636,-106.077,0.7,"verde","zona_segura","Segura de día."),
        ("zj001","Zona Crítica – Col. Anáhuac",31.760,-106.500,1.5,"negro","homicidio","Alta violencia en Juárez."),
        ("zj002","Zona Crítica – Col. Chaveña",31.750,-106.490,1.2,"negro","homicidio","Alta peligrosidad."),
        ("zj003","Zona Crítica – Col. Revolución",31.742,-106.480,1.0,"negro","robo_violento","Alta delincuencia nocturna."),
        ("zj004","Alerta – Centro Histórico Nocturno",31.738,-106.487,0.8,"rojo","asalto","Precaución de noche."),
        ("zj005","Precaución – Zaragoza Sur",31.685,-106.405,1.2,"rojo","robo","Colonias periféricas."),
        ("zj006","Alerta – Valle del Bravo",31.765,-106.440,1.0,"rojo","robo_vehiculo","Robo de vehículos."),
        ("zj007","Moderado – Zona PRONAF",31.718,-106.472,0.8,"amarillo","carterismo","Cuida pertenencias."),
        ("zj008","Moderado – Central Camiones Juárez",31.730,-106.479,0.6,"amarillo","estafa","Estafas a viajeros."),
        ("zj009","Zona Segura – Galerías Tec",31.697,-106.430,1.0,"verde","zona_segura","Zona comercial vigilada."),
        ("zj010","Zona Segura – PRONAF Norte",31.722,-106.468,0.8,"verde","zona_segura","Presencia policial."),
        ("zj011","Zona Segura – Campestre Juárez",31.695,-106.420,1.2,"verde","zona_segura","Colonia residencial."),
        ("zj012","Zona Segura – Partido Romero",31.698,-106.432,1.0,"verde","zona_segura","Patrullaje constante."),
    ]
    for z in zones:
        zid,name,lat,lon,radius,level,ztype,desc = z
        c.execute(
            'INSERT OR IGNORE INTO risk_zones '
            '(id,name,lat,lon,radius_km,level,color,zone_type,description,source) '
            "VALUES (?,?,?,?,?,?,?,?,?,'seed')",
            (zid,name,lat,lon,radius,level,ZC[level],ztype,desc))
    conn.commit(); conn.close()
    print("✅ 22 zonas cargadas")

def seed_ads():
    conn = sqlite3.connect(DB_FILE); c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM ads")
    if c.fetchone()[0] > 0: conn.close(); return
    ads = [
        ("¡Llena el tanque con OXXO Gas!",
         "Más de 20 estaciones en Chihuahua y Juárez.",
         "Ver ubicaciones","https://oxxogas.com","⛽","OXXO Gas","vehiculo","both",
         (datetime.now()+timedelta(days=90)).isoformat()),
        ("Star Médica – Tu salud primero",
         "Urgencias 24 hrs. Chihuahua y Juárez.",
         "Llamar ahora","tel:6144399000","🏥","Star Médica","salud","both",
         (datetime.now()+timedelta(days=90)).isoformat()),
        ("HEB – Frescura garantizada",
         "Supermercados en Plaza Sendero y Galerías Tec.",
         "Ver ubicación","#","🛒","HEB México","compras","both",
         (datetime.now()+timedelta(days=90)).isoformat()),
        ("Cinépolis – Vive el cine",
         "4DX y VIP en Chihuahua y Juárez.",
         "Ver cartelera","https://cinepolis.com","🎬","Cinépolis","entretenimiento","both",
         (datetime.now()+timedelta(days=90)).isoformat()),
        ("¿Tienes un negocio? Aparece en ZETA",
         "Llega a miles de usuarios con tu pin patrocinado.",
         "Anunciarme","mailto:ads@zetapro.mx","📍","ZETA Ads","promo","both",
         (datetime.now()+timedelta(days=90)).isoformat()),
    ]
    for a in ads:
        title,body,cta,url,icon,sponsor,cat,city,ends = a
        c.execute(
            'INSERT INTO ads (title,body,cta,url,icon,sponsor_name,category,city,ends_at) '
            'VALUES (?,?,?,?,?,?,?,?,?)',
            (title,body,cta,url,icon,sponsor,cat,city,ends))
    conn.commit(); conn.close()

seed_tips()
seed_places()
seed_zones()
seed_ads()

@app.route('/api/auth/register', methods=['POST'])
def register():
    try:
        data  = request.json
        email = data.get('email','').lower().strip()
        name  = data.get('name','').strip()
        photo = data.get('photo','')
        phone = data.get('phone','')
        lang  = data.get('language','es')
        if not email or '@' not in email:
            return jsonify({"status":"error","message":"Email inválido"}), 400
        if len(name) < 2:
            return jsonify({"status":"error","message":"Nombre requerido"}), 400
        if photo: photo = compress_image(photo,(400,400),80)
        conn = sqlite3.connect(DB_FILE); c = conn.cursor()
        c.execute("SELECT id,name,email,photo,reports_count,rating,is_premium,language "
                  "FROM users WHERE email=?", (email,))
        ex = c.fetchone()
        if ex:
            c.execute("UPDATE users SET last_login=? WHERE id=?", (datetime.now(),ex[0]))
            conn.commit(); conn.close()
            return jsonify({"status":"success","user":{
                "id":ex[0],"name":ex[1],"email":ex[2],"photo":ex[3],
                "reports_count":ex[4],"rating":ex[5],
                "is_premium":bool(ex[6]),"language":ex[7]}})
        uid = generate_id('user_')
        c.execute("INSERT INTO users (id,email,name,photo,phone,last_login,language) "
                  "VALUES (?,?,?,?,?,?,?)",
                  (uid,email,name,photo,phone,datetime.now(),lang))
        conn.commit(); conn.close()
        return jsonify({"status":"success","user":{
            "id":uid,"email":email,"name":name,"photo":photo,
            "reports_count":0,"rating":5.0,"is_premium":False,"language":lang}})
    except Exception as e:
        return jsonify({"status":"error","message":str(e)}), 500

@app.route('/api/user/preferences', methods=['POST'])
def save_preferences():
    try:
        data  = request.json
        uid   = data.get('user_id')
        lang  = data.get('language')
        theme = data.get('theme')
        if not uid: return jsonify({"status":"error"}), 400
        conn = sqlite3.connect(DB_FILE); c = conn.cursor()
        if lang:  c.execute("UPDATE users SET language=? WHERE id=?",  (lang,uid))
        if theme: c.execute("UPDATE users SET theme=? WHERE id=?",     (theme,uid))
        conn.commit(); conn.close()
        return jsonify({"status":"success"})
    except Exception as e:
        return jsonify({"status":"error","message":str(e)}), 500

@app.route('/api/geocode/forward', methods=['GET'])
def geocode_forward():
    """Busca cualquier dirección, calle o colonia — 100% gratis."""
    q = request.args.get('q','').strip()
    if len(q) < 3:
        return jsonify({"status":"error","message":"Query muy corto"}), 400
    try:
        if HAS_REQUESTS:
            resp = req_lib.get(
                'https://nominatim.openstreetmap.org/search',
                params={'q': q + ', México', 'format':'json', 'limit':8,
                        'accept-language':'es', 'countrycodes':'mx',
                        'addressdetails':1},
                headers={'User-Agent':'ZetaPro/2.2'},
                timeout=8)
            results = resp.json()
            out = []
            for r in results:
                a = r.get('address',{})
                short = (a.get('road') or a.get('suburb') or
                         a.get('village') or r.get('display_name',''))[:80]
                out.append({"name":r.get('display_name',''),
                            "short": short,
                            "lat": float(r['lat']),
                            "lon": float(r['lon']),
                            "type": r.get('type','')})
            return jsonify({"status":"success","results":out})
        if geolocator:
            locs = geolocator.geocode(q+', México', exactly_one=False, limit=5, language='es')
            if locs:
                out=[{"name":l.address,"short":l.address[:60],
                      "lat":l.latitude,"lon":l.longitude} for l in locs]
                return jsonify({"status":"success","results":out})
        return jsonify({"status":"error","message":"Geocoding no disponible"}), 503
    except Exception as e:
        return jsonify({"status":"error","message":str(e)}), 500

@app.route('/api/geocode/reverse', methods=['POST'])
def rev_geocode():
    try:
        data = request.json; lat = data.get('lat'); lon = data.get('lon')
        addr = "Chihuahua, Chih."
        if HAS_REQUESTS:
            try:
                resp = req_lib.get('https://nominatim.openstreetmap.org/reverse',
                    params={'lat':lat,'lon':lon,'format':'json','accept-language':'es'},
                    headers={'User-Agent':'ZetaPro/2.2'}, timeout=6)
                d = resp.json(); a = d.get('address',{})
                addr = ", ".join(filter(None,[a.get('road',''),a.get('suburb',''),
                                              a.get('city','')])) or addr
            except: pass
        elif geolocator:
            try:
                loc = geolocator.reverse(f"{lat},{lon}",language='es',timeout=6)
                if loc:
                    a = loc.raw.get('address',{})
                    addr = ", ".join(filter(None,[a.get('road',''),a.get('suburb','')])) or addr
            except: pass
        return jsonify({"status":"success","address":addr})
    except Exception as e:
        return jsonify({"status":"error","message":str(e)}), 500

@app.route('/api/places/search', methods=['GET'])
def search_places():
    try:
        query  = request.args.get('q','').strip()
        ptype  = request.args.get('type')
        city   = request.args.get('city')
        lat    = request.args.get('lat')
        lon    = request.args.get('lon')
        radius = float(request.args.get('radius',200))
        conn   = sqlite3.connect(DB_FILE); c = conn.cursor()
        sql    = ("SELECT id,name,type,lat,lon,address,phone,description,"
                  "rating,total_reviews,price_level,hours,tags,city,"
                  "is_sponsored,sponsor_tier FROM places WHERE 1=1")
        params = []
        if query:
            lq = f'%{query.lower()}%'
            sql += " AND (LOWER(name) LIKE ? OR LOWER(description) LIKE ? "
            sql += "OR LOWER(tags) LIKE ? OR LOWER(address) LIKE ?)"
            params += [lq,lq,lq,lq]
        if ptype: sql += " AND LOWER(type) LIKE ?"; params.append(f'%{ptype.lower()}%')
        if city:  sql += " AND city=?"; params.append(city.lower())
        sql += " ORDER BY is_sponsored DESC, rating DESC, total_reviews DESC LIMIT 300"
        c.execute(sql, params)
        out = []
        for row in c.fetchall():
            p = {"id":row[0],"name":row[1],"type":row[2],"lat":row[3],"lon":row[4],
                 "address":row[5],"phone":row[6],"description":row[7],"rating":row[8],
                 "total_reviews":row[9],"price_level":row[10],"hours":row[11],
                 "tags":row[12],"city":row[13],
                 "is_sponsored":bool(row[14]),"sponsor_tier":row[15],
                 "source":"zeta"}
            if lat and lon:
                dist = get_distance(float(lat),float(lon),row[3],row[4])
                if dist <= radius: p['distance_km'] = round(dist,2); out.append(p)
            else: out.append(p)
        conn.close()
        return jsonify(out)
    except Exception as e:
        return jsonify({"status":"error","message":str(e)}), 500

@app.route('/api/places/<pid>/reviews', methods=['POST'])
def add_review(pid):
    try:
        data   = request.json
        uid    = data.get('user_id')
        rating = int(data.get('rating',5))
        comment= data.get('comment','').strip()
        imgs   = data.get('images',[])
        if not 1 <= rating <= 5:
            return jsonify({"status":"error","message":"Rating 1-5"}), 400
        imgs2 = [compress_image(i) for i in imgs[:3]]
        conn  = sqlite3.connect(DB_FILE); c = conn.cursor()
        rid   = generate_id('rev_')
        c.execute("INSERT INTO reviews (id,place_id,user_id,rating,comment,images) "
                  "VALUES (?,?,?,?,?,?)", (rid,pid,uid,rating,comment,json.dumps(imgs2)))
        c.execute("SELECT AVG(rating),COUNT(*) FROM reviews WHERE place_id=?",(pid,))
        avg,tot = c.fetchone()
        c.execute("UPDATE places SET rating=?,total_reviews=? WHERE id=?",
                  (round(avg,1),tot,pid))
        conn.commit(); conn.close()
        return jsonify({"status":"success","review_id":rid,
                        "new_rating":round(avg,1),"total_reviews":tot})
    except Exception as e:
        return jsonify({"status":"error","message":str(e)}), 500

@app.route('/api/zones/risk', methods=['GET'])
def get_zones():
    try:
        conn = sqlite3.connect(DB_FILE); c = conn.cursor()
        c.execute("SELECT id,name,lat,lon,radius_km,level,color,zone_type,description,"
                  "incident_count FROM risk_zones WHERE active=1 "
                  "AND (expires_at IS NULL OR expires_at>?) "
                  "ORDER BY CASE level WHEN 'negro' THEN 1 WHEN 'rojo' THEN 2 "
                  "WHEN 'amarillo' THEN 3 ELSE 4 END", (datetime.now(),))
        zones = [{"id":r[0],"name":r[1],"lat":r[2],"lon":r[3],"radius_km":r[4],
                  "level":r[5],"color":r[6],"zone_type":r[7],"description":r[8],
                  "incident_count":r[9]} for r in c.fetchall()]
        conn.close()
        return jsonify({"status":"success","zones":zones})
    except Exception as e:
        return jsonify({"status":"error","message":str(e)}), 500

@app.route('/api/zones/check', methods=['POST'])
def check_zone():
    try:
        data  = request.json
        lat   = float(data.get('lat',0)); lon = float(data.get('lon',0))
        uid   = data.get('user_id')
        level = risk_at(lat,lon); zname,_ = zone_name_at(lat,lon)
        if uid:
            conn = sqlite3.connect(DB_FILE); c = conn.cursor()
            c.execute("INSERT INTO zone_history (user_id,zone_level,zone_name,lat,lon) "
                      "VALUES (?,?,?,?,?)", (uid,level,zname,lat,lon))
            conn.commit(); conn.close()
        return jsonify({"status":"success","level":level,
                        "color":ZONE_COLORS.get(level,"#10b981"),"zone_name":zname,
                        "risk":{"level":level,"color":ZONE_COLORS.get(level,"#10b981"),
                                "zone_name":zname}})
    except Exception as e:
        return jsonify({"status":"error","message":str(e)}), 500

@app.route('/api/zones/add', methods=['POST'])
def add_zone():
    try:
        data  = request.json; level = data.get('level','rojo')
        if level not in ZONE_COLORS:
            return jsonify({"status":"error","message":"Nivel inválido"}), 400
        exp = datetime.now() + timedelta(hours=int(data.get('expires_hours',48)))
        zid = generate_id('zone_')
        conn = sqlite3.connect(DB_FILE); c = conn.cursor()
        c.execute("INSERT INTO risk_zones (id,name,lat,lon,radius_km,level,color,"
                  "zone_type,description,expires_at,source) "
                  "VALUES (?,?,?,?,?,?,?,?,?,?,'admin')",
                  (zid,data.get('name','Zona'),float(data.get('lat',0)),
                   float(data.get('lon',0)),float(data.get('radius_km',0.5)),
                   level,ZONE_COLORS[level],data.get('zone_type','incidente'),
                   data.get('description',''),exp))
        conn.commit(); conn.close()
        return jsonify({"status":"success","zone_id":zid})
    except Exception as e:
        return jsonify({"status":"error","message":str(e)}), 500

@app.route('/api/zones/delete/<zid>', methods=['DELETE'])
def delete_zone(zid):
    try:
        conn = sqlite3.connect(DB_FILE); c = conn.cursor()
        c.execute("UPDATE risk_zones SET active=0 WHERE id=?", (zid,))
        conn.commit(); conn.close()
        return jsonify({"status":"success"})
    except Exception as e:
        return jsonify({"status":"error","message":str(e)}), 500

# ── SOLICITUDES DE ZONA (usuarios proponen → admin aprueba) ─────
@app.route('/api/zones/request', methods=['POST'])
def request_zone():
    """Cualquier usuario puede proponer una zona. Va a revisión del admin."""
    try:
        data = request.json
        uid  = data.get('user_id','anonymous')
        lat  = float(data.get('lat',0)); lon = float(data.get('lon',0))
        if not data.get('name') or not data.get('level'):
            return jsonify({"status":"error","message":"Nombre y nivel requeridos"}), 400
        imgs = [compress_image(i,(800,800)) for i in data.get('evidence_images',[])[:3]]
        rid  = generate_id('zreq_')
        conn = sqlite3.connect(DB_FILE); c = conn.cursor()
        c.execute("INSERT INTO zone_requests "
                  "(id,user_id,name,lat,lon,radius_km,level,description,evidence_images) "
                  "VALUES (?,?,?,?,?,?,?,?,?)",
                  (rid,uid,data['name'],lat,lon,
                   float(data.get('radius_km',0.5)),data['level'],
                   data.get('description',''),json.dumps(imgs)))
        conn.commit(); conn.close()
        return jsonify({"status":"success","request_id":rid,
                        "message":"Solicitud enviada. El equipo ZETA la revisará en 24h."})
    except Exception as e:
        return jsonify({"status":"error","message":str(e)}), 500

@app.route('/api/zones/requests', methods=['GET'])
def list_zone_requests():
    if not admin_ok(request):
        return jsonify({"status":"error","message":"No autorizado"}), 403
    conn = sqlite3.connect(DB_FILE); c = conn.cursor()
    c.execute("SELECT id,user_id,name,lat,lon,radius_km,level,description,"
              "evidence_images,status,created_at FROM zone_requests "
              "WHERE status='pending' ORDER BY created_at DESC LIMIT 50")
    reqs = [{"id":r[0],"user_id":r[1],"name":r[2],"lat":r[3],"lon":r[4],
             "radius_km":r[5],"level":r[6],"description":r[7],
             "evidence_images":json.loads(r[8] or '[]'),
             "status":r[9],"created_at":r[10]} for r in c.fetchall()]
    conn.close()
    return jsonify({"status":"success","requests":reqs})

@app.route('/api/zones/requests/<rid>/action', methods=['POST'])
def action_zone_request(rid):
    if not admin_ok(request):
        return jsonify({"status":"error","message":"No autorizado"}), 403
    data   = request.json; action = data.get('action','reject')
    status = 'approved' if action == 'approve' else 'rejected'
    conn   = sqlite3.connect(DB_FILE); c = conn.cursor()
    c.execute("UPDATE zone_requests SET status=?,reviewed_at=?,admin_note=? WHERE id=?",
              (status,datetime.now(),data.get('note',''),rid))
    if action == 'approve':
        c.execute("SELECT name,lat,lon,radius_km,level,description FROM zone_requests "
                  "WHERE id=?", (rid,))
        req = c.fetchone()
        if req:
            zid = generate_id('zone_')
            exp = datetime.now() + timedelta(hours=int(data.get('hours',72)))
            c.execute("INSERT INTO risk_zones "
                      "(id,name,lat,lon,radius_km,level,color,zone_type,"
                      "description,expires_at,source) "
                      "VALUES (?,?,?,?,?,?,?,?,?,?,'user_request')",
                      (zid,req[0],req[1],req[2],req[3],req[4],
                       ZONE_COLORS.get(req[4],'#888'),'reporte',req[5],exp))
    conn.commit(); conn.close()
    return jsonify({"status":"success","action":action})

@app.route('/api/zones/history/<uid>', methods=['GET'])
def zone_history(uid):
    try:
        period = request.args.get('period','month')
        cutoff = {"month":30,"year":365,"all":3650}.get(period,30)
        since  = datetime.now() - timedelta(days=cutoff)
        conn   = sqlite3.connect(DB_FILE); c = conn.cursor()
        c.execute("SELECT zone_level,COUNT(*) FROM zone_history "
                  "WHERE user_id=? AND transited_at>? GROUP BY zone_level", (uid,since))
        totals = {r[0]:{"count":r[1],"color":ZONE_COLORS.get(r[0],"#888")}
                  for r in c.fetchall()}
        c.execute("SELECT strftime('%Y-%m',transited_at) as mo,zone_level,COUNT(*) "
                  "FROM zone_history WHERE user_id=? AND transited_at>? "
                  "GROUP BY mo,zone_level ORDER BY mo DESC LIMIT 72", (uid,since))
        monthly = {}
        for mo,lv,cnt in c.fetchall():
            if mo not in monthly: monthly[mo]={"negro":0,"rojo":0,"amarillo":0,"verde":0}
            monthly[mo][lv] = cnt
        c.execute("SELECT zone_level,zone_name,lat,lon,transited_at FROM zone_history "
                  "WHERE user_id=? ORDER BY transited_at DESC LIMIT 20", (uid,))
        recent=[{"color":r[0],"name":r[1] or r[0],"lat":r[2],"lon":r[3],"at":r[4]}
                for r in c.fetchall()]
        total  = sum(v['count'] for v in totals.values())
        safe   = totals.get('verde',{}).get('count',0)
        safety = round(safe/total*100) if total else 0
        c.execute("SELECT COUNT(DISTINCT DATE(transited_at)) FROM zone_history "
                  "WHERE user_id=? AND zone_level NOT IN ('negro','rojo')", (uid,))
        streak = c.fetchone()[0]; conn.close()
        return jsonify({"status":"success","period":period,"totals":totals,
                        "monthly":monthly,"recent":recent,"total":total,
                        "safety_score":safety,"safe_streak_days":streak})
    except Exception as e:
        return jsonify({"status":"error","message":str(e)}), 500

@app.route('/api/history/zones/record', methods=['POST'])
def record_zone():
    try:
        data  = request.json; uid = data.get('user_id')
        lat   = float(data.get('lat',0)); lon = float(data.get('lon',0))
        level = risk_at(lat,lon); zname,_ = zone_name_at(lat,lon)
        conn  = sqlite3.connect(DB_FILE); c = conn.cursor()
        c.execute("INSERT INTO zone_history (user_id,zone_level,zone_name,lat,lon) "
                  "VALUES (?,?,?,?,?)", (uid,level,zname,lat,lon))
        conn.commit(); conn.close()
        return jsonify({"status":"success","level":level,"zone_name":zname})
    except Exception as e:
        return jsonify({"status":"error","message":str(e)}), 500

@app.route('/api/reports/submit', methods=['POST'])
def submit_report():
    try:
        data = request.json; desc = data.get('description','').strip()
        cat  = data.get('category','other'); sev = data.get('severity','low')
        lat  = data.get('lat'); lon = data.get('lon'); uid = data.get('user_id')
        imgs = data.get('images',[])
        if len(desc) < 15: return jsonify({"status":"error","message":"Mínimo 15 caracteres"}), 400
        if not lat or not lon: return jsonify({"status":"error","message":"Ubicación requerida"}), 400
        imgs2 = [compress_image(i,(1200,1200)) for i in imgs[:5]]
        addr  = "Chihuahua / Juárez, Chih."
        if HAS_REQUESTS:
            try:
                resp = req_lib.get('https://nominatim.openstreetmap.org/reverse',
                    params={'lat':lat,'lon':lon,'format':'json','accept-language':'es'},
                    headers={'User-Agent':'ZetaPro/2.2'},timeout=5)
                a = resp.json().get('address',{})
                addr = ", ".join(filter(None,[a.get('road',''),a.get('suburb','')])) or addr
            except: pass
        elif geolocator:
            try:
                loc = geolocator.reverse(f"{lat},{lon}",language='es',timeout=5)
                if loc:
                    a = loc.raw.get('address',{})
                    addr = ", ".join(filter(None,[a.get('road',''),a.get('suburb','')])) or addr
            except: pass
        # Scoring de credibilidad
        s = 0.40; dl = desc.lower()
        for k in ['policía','patrulla','ambulancia','accidente','robo','asalto','balacera','herido']:
            if k in dl: s += 0.07
        for k in ['creo','parece','supongo','dicen','escuché']:
            if k in dl: s -= 0.10
        if len(desc) > 80:  s += 0.08
        if imgs2:            s += 0.15
        if sev=='high' and imgs2:    s += 0.05
        if sev=='high' and not imgs2: s -= 0.15
        score = round(min(1.0,max(0.0,s)),2)
        conn = sqlite3.connect(DB_FILE); c = conn.cursor()
        rid  = generate_id('rep_')
        c.execute("INSERT INTO reports (id,user_id,description,category,severity,"
                  "lat,lon,address,images,status,verified,verified_by) "
                  "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                  (rid,uid,desc,cat,sev,float(lat),float(lon),addr,json.dumps(imgs2),
                   'active' if score>=0.75 else 'pending',
                   1 if score>=0.75 else 0,
                   'auto_ai' if score>=0.75 else None))
        if uid: c.execute("UPDATE users SET reports_count=reports_count+1 WHERE id=?",(uid,))
        conn.commit(); conn.close()
        return jsonify({"status":"success","report_id":rid,
                        "verification_score":score,"auto_verified":score>=0.75})
    except Exception as e:
        return jsonify({"status":"error","message":str(e)}), 500

@app.route('/api/reports/list', methods=['GET'])
def list_reports():
    try:
        ver    = request.args.get('verified','true')=='true'
        days   = int(request.args.get('days',30))
        lat    = request.args.get('lat'); lon = request.args.get('lon')
        radius = float(request.args.get('radius',200))
        cutoff = datetime.now()-timedelta(days=days)
        conn   = sqlite3.connect(DB_FILE); c = conn.cursor()
        sql    = ("SELECT r.id,r.user_id,r.description,r.category,r.severity,"
                  "r.lat,r.lon,r.address,r.images,r.created_at,r.verified,r.status,"
                  "r.upvotes,r.downvotes,u.name,u.photo "
                  "FROM reports r LEFT JOIN users u ON r.user_id=u.id "
                  "WHERE r.created_at>?")
        params = [cutoff]
        if ver: sql += " AND r.verified=1"
        sql += " ORDER BY r.created_at DESC LIMIT 300"
        c.execute(sql,params)
        out = []
        for r in c.fetchall():
            if lat and lon and get_distance(float(lat),float(lon),r[5],r[6])>radius: continue
            out.append({"id":r[0],"user_id":r[1],"description":r[2],"category":r[3],
                        "severity":r[4],"lat":r[5],"lon":r[6],"address":r[7],
                        "images":json.loads(r[8]) if r[8] else [],"created_at":r[9],
                        "verified":bool(r[10]),"status":r[11],"upvotes":r[12],
                        "downvotes":r[13],"user_name":r[14],"user_photo":r[15]})
        conn.close()
        return jsonify({"status":"success","reports":out,"total":len(out)})
    except Exception as e:
        return jsonify({"status":"error","message":str(e)}), 500

@app.route('/api/reports/vote/<rid>', methods=['POST'])
def vote_report(rid):
    try:
        data = request.json; uid = data.get('user_id'); vt = data.get('vote_type')
        if vt not in ('up','down'): return jsonify({"status":"error"}), 400
        conn = sqlite3.connect(DB_FILE); c = conn.cursor()
        c.execute("SELECT vote_type FROM report_votes WHERE report_id=? AND user_id=?",(rid,uid))
        ex = c.fetchone()
        if ex:
            c.execute("UPDATE report_votes SET vote_type=? WHERE report_id=? AND user_id=?",(vt,rid,uid))
            c.execute(f"UPDATE reports SET {ex[0]}votes={ex[0]}votes-1 WHERE id=?",(rid,))
        else:
            c.execute("INSERT INTO report_votes (report_id,user_id,vote_type) VALUES (?,?,?)",(rid,uid,vt))
        c.execute(f"UPDATE reports SET {vt}votes={vt}votes+1 WHERE id=?",(rid,))
        conn.commit()
        c.execute("SELECT upvotes,downvotes FROM reports WHERE id=?",(rid,))
        up,dn = c.fetchone(); conn.close()
        return jsonify({"status":"success","upvotes":up,"downvotes":dn})
    except Exception as e:
        return jsonify({"status":"error","message":str(e)}), 500

@app.route('/api/tips/contextual', methods=['POST'])
def tips_contextual():
    try:
        data  = request.json
        lat   = float(data.get('lat',28.635)); lon = float(data.get('lon',-106.077))
        level = risk_at(lat,lon)
        conn  = sqlite3.connect(DB_FILE); c = conn.cursor()
        c.execute("SELECT tip_text,tip_category,icon FROM security_tips "
                  "WHERE active=1 AND (zone_level=? OR zone_level IS NULL) "
                  "ORDER BY RANDOM() LIMIT 3", (level,))
        tips  = [{"tip":r[0],"text":r[0],"category":r[1],"icon":r[2]} for r in c.fetchall()]
        conn.close()
        return jsonify({"status":"success","tips":tips,"zone_level":level})
    except Exception as e:
        return jsonify({"status":"error","message":str(e)}), 500

@app.route('/api/tips/all', methods=['GET'])
def tips_all():
    try:
        conn = sqlite3.connect(DB_FILE); c = conn.cursor()
        c.execute("SELECT tip_text,tip_category,icon FROM security_tips "
                  "WHERE active=1 ORDER BY priority,RANDOM()")
        tips = [{"tip":r[0],"text":r[0],"category":r[1],"icon":r[2]} for r in c.fetchall()]
        conn.close()
        return jsonify({"status":"success","tips":tips})
    except Exception as e:
        return jsonify({"status":"error","message":str(e)}), 500

@app.route('/api/routes/calculate', methods=['POST'])
def calc_route():
    try:
        data = request.json; ori = data.get('origin',''); dst = data.get('destination','')
        uid  = data.get('user_id')
        olat,olon = 28.6353,-106.0886; dlat,dlon = None,None

        def try_coords(s):
            if s and ',' in s:
                try:
                    p = s.split(',')
                    return float(p[0].strip()), float(p[1].strip())
                except: pass
            return None, None

        la,lo = try_coords(ori)
        if la: olat,olon = la,lo
        la,lo = try_coords(dst)
        if la: dlat,dlon = la,lo

        if not dlat:
            dlat,dlon = get_coords_free(dst)
            if not dlat: dlat,dlon = 31.7380,-106.4870

        # Intentar OSRM (rutas reales gratis)
        osrm_geo = None; real_dist = None; real_dur = None
        if HAS_REQUESTS:
            try:
                r = req_lib.get(
                    f'https://router.project-osrm.org/route/v1/driving/'
                    f'{olon},{olat};{dlon},{dlat}',
                    params={'overview':'full','geometries':'geojson'},
                    timeout=8)
                rd = r.json()
                if rd.get('code') == 'Ok':
                    route      = rd['routes'][0]
                    osrm_geo   = route['geometry']
                    real_dist  = round(route['distance']/1000,2)
                    real_dur   = int(route['duration']/60)
            except: pass

        dist  = real_dist if real_dist else get_distance(olat,olon,dlat,dlon)
        dur   = real_dur  if real_dur  else int(dist*3)
        level = risk_at((olat+dlat)/2,(olon+dlon)/2)
        geo   = osrm_geo  if osrm_geo  else {"type":"LineString","coordinates":[[olon,olat],[dlon,dlat]]}
        rf    = {"verde":1.0,"amarillo":1.15,"rojo":1.3,"negro":1.5}
        f     = rf.get(level,1.0)
        tops  = [
            {"mode":"Automóvil",   "icon":"🚗","time":f"{int(dur*f)} min",      "distance":f"{round(dist,1)} km","risk":level},
            {"mode":"Motocicleta", "icon":"🏍️","time":f"{int(dur*.85*f)} min",  "distance":f"{round(dist,1)} km","risk":level},
            {"mode":"Bicicleta",   "icon":"🚴","time":f"{int((dist/15)*60)} min","distance":f"{round(dist,1)} km","risk":"verde"},
            {"mode":"Caminando",   "icon":"🚶","time":f"{int((dist/5)*60)} min", "distance":f"{round(dist,1)} km","risk":level},
        ]
        warns = []
        if level in('rojo','negro'): warns.append({"message":f"⚠️ Ruta atraviesa zona {level.upper()}","severity":"CRITICAL"})
        elif level=='amarillo': warns.append({"message":"🟡 Zona de riesgo moderado en la ruta","severity":"HIGH"})
        if uid:
            conn = sqlite3.connect(DB_FILE); c = conn.cursor()
            c.execute("INSERT INTO trips (id,user_id,origin_name,dest_name,origin_lat,origin_lon,"
                      "dest_lat,dest_lon,distance_km,duration_min,risk_level) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                      (generate_id('trip_'),uid,ori,dst,olat,olon,dlat,dlon,round(dist,2),dur,level))
            c.execute("UPDATE users SET trips_count=trips_count+1,total_km=total_km+? WHERE id=?",
                      (round(dist,2),uid))
            conn.commit(); conn.close()
        return jsonify({"status":"success",
                        "origin":{"lat":olat,"lon":olon,"name":ori},
                        "destination":{"lat":dlat,"lon":dlon,"name":dst},
                        "risk_level":level,"risk_color":ZONE_COLORS.get(level,"#10b981"),
                        "distance_km":round(dist,2),"duration_min":dur,
                        "transport_options":tops,"route_geometry":geo,"warnings":warns,
                        "routing_mode":"osrm" if osrm_geo else "straight"})
    except Exception as e:
        return jsonify({"status":"error","message":str(e)}), 500

@app.route('/api/ai/chat', methods=['POST'])
def ai_chat():
    """
    Asistente IA multi-función con Claude.
    Variable requerida en Railway: ANTHROPIC_API_KEY=sk-ant-...
    action: 'chat' | 'moderate' | 'analyze_zone'
    """
    if not ANTHROPIC_KEY:
        return jsonify({"status":"error",
                        "message":"IA no configurada. Agrega ANTHROPIC_API_KEY en Railway."}), 503
    if not HAS_REQUESTS:
        return jsonify({"status":"error","message":"requests no instalado"}), 503
    try:
        data     = request.json
        messages = data.get('messages',[])
        context  = data.get('context',{})
        action   = data.get('action','chat')

        if action == 'moderate':
            system = (
                "Eres el moderador IA de ZETA. Analiza el reporte ciudadano y determina:\n"
                "1. Si debe APROBARSE o RECHAZARSE\n"
                "2. Nivel de credibilidad 0-100\n"
                "3. Razón breve\n\n"
                'Responde SOLO en JSON válido: {"action":"approve","score":85,"reason":"texto","severity":"high"}\n'
                "Sin markdown, sin explicación extra.")
        elif action == 'analyze_zone':
            system = (
                "Eres analista de seguridad de ZETA para Chihuahua y Ciudad Juárez.\n"
                "Analiza la solicitud de zona de riesgo y decide si aprobarla.\n"
                'Responde SOLO en JSON: {"action":"approve","level":"rojo","reason":"texto","hours":72}')
        else:
            system = (
                "Eres ZETA IA, el asistente inteligente de navegación táctica para "
                "Chihuahua y Ciudad Juárez, México.\n\n"
                "Funciones:\n"
                "- Navegación segura y rutas recomendadas\n"
                "- Consejos de seguridad por zona\n"
                "- Información de lugares y horarios\n"
                "- Ayuda para usar la app ZETA\n"
                "- Análisis de situaciones de seguridad\n\n"
                f"Contexto actual:\n"
                f"- Zona del usuario: {context.get('zone_level','desconocida')}\n"
                f"- Ciudad: {context.get('city','Chihuahua')}\n"
                f"- Es premium: {context.get('is_premium',False)}\n"
                f"- Hora: {datetime.now().strftime('%H:%M')}\n\n"
                "Reglas:\n"
                "- Detecta el idioma del usuario y responde en ese idioma\n"
                "- Respuestas concisas (máx 3 párrafos)\n"
                "- Si preguntan sobre emergencias, incluye 911 siempre\n"
                "- Nunca inventes datos de incidentes reales")

        resp = req_lib.post(
            'https://api.anthropic.com/v1/messages',
            headers={'Content-Type':'application/json',
                     'x-api-key':ANTHROPIC_KEY,
                     'anthropic-version':'2023-06-01'},
            json={"model":"claude-haiku-4-5-20251001",
                  "max_tokens":600,"system":system,
                  "messages":messages[-8:]},
            timeout=30)

        result = resp.json()
        if resp.status_code != 200:
            return jsonify({"status":"error",
                            "message":result.get('error',{}).get('message','Error AI')}), 500

        text   = result['content'][0]['text']
        tokens = result.get('usage',{}).get('output_tokens',0)

        # Log
        conn = sqlite3.connect(DB_FILE); c = conn.cursor()
        c.execute("INSERT INTO ai_logs (user_id,role,content,tokens,action) VALUES (?,?,?,?,?)",
                  (context.get('user_id'),'assistant',text[:500],tokens,action))
        conn.commit(); conn.close()

        return jsonify({"status":"success","message":text,"tokens":tokens,"action":action})
    except Exception as e:
        return jsonify({"status":"error","message":str(e)}), 500

@app.route('/api/ads/get', methods=['GET'])
def get_ad():
    """Devuelve un anuncio. Los usuarios premium no ven anuncios."""
    try:
        uid  = request.args.get('user_id')
        city = request.args.get('city','both')
        # Verificar si es premium
        if uid:
            conn = sqlite3.connect(DB_FILE); c = conn.cursor()
            c.execute("SELECT is_premium,premium_until FROM users WHERE id=?", (uid,))
            row = c.fetchone(); conn.close()
            if row and row[0]:
                expiry = row[1]
                if expiry is None or datetime.fromisoformat(str(expiry)) > datetime.now():
                    return jsonify({"status":"success","ad":None,"premium":True})
        conn = sqlite3.connect(DB_FILE); c = conn.cursor()
        c.execute("SELECT id,title,body,cta,url,icon,sponsor_name,category "
                  "FROM ads WHERE active=1 AND (ends_at IS NULL OR ends_at>?) "
                  "AND (city=? OR city='both') "
                  "ORDER BY priority DESC, RANDOM() LIMIT 1",
                  (datetime.now(),city))
        row = c.fetchone()
        if not row: conn.close(); return jsonify({"status":"success","ad":None})
        ad = {"id":row[0],"title":row[1],"body":row[2],"cta":row[3],
              "url":row[4],"icon":row[5],"sponsor":row[6],"category":row[7]}
        c.execute("UPDATE ads SET impressions=impressions+1 WHERE id=?",(row[0],))
        conn.commit(); conn.close()
        return jsonify({"status":"success","ad":ad,"premium":False})
    except Exception as e:
        return jsonify({"status":"error","message":str(e)}), 500

@app.route('/api/ads/click/<int:aid>', methods=['POST'])
def ad_click(aid):
    try:
        conn = sqlite3.connect(DB_FILE); c = conn.cursor()
        c.execute("UPDATE ads SET clicks=clicks+1 WHERE id=?",(aid,))
        conn.commit(); conn.close()
        return jsonify({"status":"success"})
    except: return jsonify({"status":"error"}), 500

@app.route('/api/premium/activate', methods=['POST'])
def activate_premium():
    """
    Activa Premium con código promo.
    En producción: reemplaza por webhook de Stripe/MercadoPago.
    """
    try:
        data = request.json; uid = data.get('user_id'); code = data.get('promo_code','').upper()
        # Códigos de demostración → en producción integra Stripe/MercadoPago
        PROMOS = {'ZETA2024':'30d', 'BETAUSER':'90d', 'PREMIUM1':'7d', 'ADMIN99':'365d'}
        if code not in PROMOS:
            return jsonify({"status":"error","message":"Código inválido"}), 400
        days  = int(PROMOS[code].replace('d',''))
        until = datetime.now() + timedelta(days=days)
        conn  = sqlite3.connect(DB_FILE); c = conn.cursor()
        c.execute("UPDATE users SET is_premium=1,premium_until=? WHERE id=?",(until,uid))
        conn.commit(); conn.close()
        return jsonify({"status":"success","premium_until":until.isoformat(),"days":days})
    except Exception as e:
        return jsonify({"status":"error","message":str(e)}), 500

@app.route('/api/premium/check', methods=['POST'])
def check_premium():
    try:
        data = request.json; uid = data.get('user_id')
        if not uid: return jsonify({"is_premium":False})
        conn = sqlite3.connect(DB_FILE); c = conn.cursor()
        c.execute("SELECT is_premium,premium_until FROM users WHERE id=?",(uid,))
        row = c.fetchone(); conn.close()
        if not row: return jsonify({"is_premium":False})
        active = bool(row[0]) and (row[1] is None or
                 datetime.fromisoformat(str(row[1])) > datetime.now())
        return jsonify({"is_premium":active,"premium_until":row[1]})
    except Exception as e:
        return jsonify({"status":"error","message":str(e)}), 500
        
@app.route('/api/sos/trigger', methods=['POST'])
def sos_trigger():
    try:
        data = request.json; uid = data.get('user_id','anon')
        lat  = data.get('lat'); lon = data.get('lon')
        if lat and lon:
            conn = sqlite3.connect(DB_FILE); c = conn.cursor()
            c.execute("INSERT INTO zone_history (user_id,zone_level,zone_name,lat,lon) "
                      "VALUES (?,?,?,?,?)", (uid,'sos','SOS_ACTIVATED',lat,lon))
            conn.commit(); conn.close()
        return jsonify({"status":"success","message":"SOS registrado"})
    except Exception as e:
        return jsonify({"status":"error","message":str(e)}), 500

@app.route('/api/stats/user/<uid>', methods=['GET'])
@app.route('/api/users/<uid>/stats', methods=['GET'])
def user_stats(uid):
    try:
        conn = sqlite3.connect(DB_FILE); c = conn.cursor()
        c.execute("SELECT name,photo,reports_count,rating,trips_count,"
                  "total_km,created_at,is_premium FROM users WHERE id=?",(uid,))
        u = c.fetchone()
        if not u: conn.close(); return jsonify({"status":"error","message":"No encontrado"}), 404
        c.execute("SELECT zone_level,COUNT(*) FROM zone_history "
                  "WHERE user_id=? AND transited_at>? GROUP BY zone_level",
                  (uid,datetime.now()-timedelta(days=30)))
        mo    = dict(c.fetchall()); total = sum(mo.values()); safe = mo.get('verde',0)
        sp    = round(safe/total*100) if total else 0
        c.execute("SELECT COUNT(DISTINCT DATE(transited_at)) FROM zone_history "
                  "WHERE user_id=? AND zone_level NOT IN ('negro','rojo')",(uid,))
        streak = c.fetchone()[0]; conn.close()
        return jsonify({"status":"success",
                        "user":{"name":u[0],"photo":u[1],"reports_count":u[2],
                                "rating":u[3],"trips_count":u[4],
                                "total_km":round(u[5] or 0,1),"member_since":u[6],
                                "is_premium":bool(u[7])},
                        "activity":{"reports":u[2]},
                        "zone_history":{"safe_pct":sp,"safe_streak":streak}})
    except Exception as e:
        return jsonify({"status":"error","message":str(e)}), 500

@app.route('/api/admin/login', methods=['POST'])
def admin_login():
    data = request.json; pin = data.get('pin','')
    if pin != ADMIN_PIN:
        return jsonify({"status":"error","message":"PIN incorrecto"}), 403
    token = hashlib.sha256(os.urandom(32)).hexdigest()[:32]
    ADMIN_TOKENS[token] = datetime.now() + timedelta(hours=8)
    return jsonify({"status":"success","token":token})

@app.route('/api/admin/reports', methods=['GET'])
def admin_list_reports():
    if not admin_ok(request): return jsonify({"status":"error","message":"No autorizado"}), 403
    conn = sqlite3.connect(DB_FILE); c = conn.cursor()
    c.execute("SELECT r.id,r.description,r.category,r.severity,r.lat,r.lon,"
              "r.address,r.images,r.created_at,u.name "
              "FROM reports r LEFT JOIN users u ON r.user_id=u.id "
              "WHERE r.status='pending' ORDER BY r.created_at DESC LIMIT 50")
    reps = [{"id":r[0],"description":r[1],"category":r[2],"severity":r[3],
             "lat":r[4],"lon":r[5],"address":r[6],
             "images":json.loads(r[7] or '[]'),"created_at":r[8],"user_name":r[9]}
            for r in c.fetchall()]
    conn.close()
    return jsonify({"status":"success","reports":reps})

@app.route('/api/admin/reports/<rid>', methods=['POST'])
def admin_report_action(rid):
    if not admin_ok(request): return jsonify({"status":"error","message":"No autorizado"}), 403
    data   = request.json; action = data.get('action','reject')
    status = 'active' if action=='approve' else 'rejected'
    conn   = sqlite3.connect(DB_FILE); c = conn.cursor()
    c.execute("UPDATE reports SET status=?,verified=?,verified_by='admin',verified_at=? WHERE id=?",
              (status,1 if action=='approve' else 0,datetime.now(),rid))
    if action=='approve':
        c.execute("SELECT lat,lon,severity FROM reports WHERE id=?",(rid,))
        rep = c.fetchone()
        if rep:
            lv  = 'rojo' if rep[2]=='high' else 'amarillo'
            zid = generate_id('zone_'); exp = datetime.now()+timedelta(hours=24)
            c.execute("INSERT INTO risk_zones (id,name,lat,lon,radius_km,level,color,"
                      "zone_type,description,expires_at,source) "
                      "VALUES (?,?,?,?,?,?,?,?,?,?,'admin_report')",
                      (zid,f"Zona Temporal – {rid[:8]}",rep[0],rep[1],0.5,
                       lv,ZONE_COLORS[lv],'reporte','Zona por reporte verificado',exp))
    conn.commit(); conn.close()
    return jsonify({"status":"success","action":action})

@app.route('/api/health', methods=['GET'])
def health():
    try:
        conn = sqlite3.connect(DB_FILE); c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM users");                  u  = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM reports WHERE verified=1");r  = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM risk_zones WHERE active=1");z = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM places");                  p  = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM places WHERE city='chihuahua'"); pchi = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM places WHERE city='juarez'");    pjua = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM zone_requests WHERE status='pending'"); zr = c.fetchone()[0]
        conn.close()
        return jsonify({"status":"healthy","version":VERSION,
                        "ai_configured":bool(ANTHROPIC_KEY),
                        "stats":{"users":u,"verified_reports":r,"active_zones":z,
                                 "places":p,"places_chihuahua":pchi,"places_juarez":pjua,
                                 "pending_zone_requests":zr},
                        "timestamp":datetime.now().isoformat()})
    except Exception as e:
        return jsonify({"status":"error","message":str(e)}), 500

@app.route('/')
def index():
    return app.send_static_file('index.html')

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    print(f"\n🛡️  ZETA PRO {VERSION}")
    print(f"   http://localhost:{port}/api/health")
    print(f"   Admin PIN    : {ADMIN_PIN}")
    print(f"   IA (Claude)  : {'✅ Configurada' if ANTHROPIC_KEY else '❌ Falta ANTHROPIC_API_KEY'}")
    print(f"   Requests     : {'✅' if HAS_REQUESTS else '❌ pip install requests'}")
    print(f"   Geopy        : {'✅' if HAS_GEOPY else '❌ pip install geopy'}")
    print(f"   Pillow       : {'✅' if HAS_PIL else '❌ pip install Pillow'}\n")
    app.run(host='0.0.0.0', port=port, debug=False)
