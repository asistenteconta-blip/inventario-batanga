import streamlit as st
import pandas as pd
import gspread
from datetime import date
from google.oauth2.service_account import Credentials
import unicodedata

# ================================
# CONFIG
# ================================

scope = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

SPREADSHEET_ID = "1BeKcPpVAc2jjoXbA6ULk8ctVxXsnYe2a9jLdWN5hcjM"

service_info = st.secrets["google_service_account"]

credentials = Credentials.from_service_account_info(
    service_info,
    scopes=scope
)

client = gspread.authorize(credentials)

@st.cache_resource(show_spinner=False)
def get_doc():
    return client.open_by_key(SPREADSHEET_ID)

doc = get_doc()

BD_TAB = "BD_productos"
INV_CO = "INVENTARIO_COCINA"
INV_SU = "INVENTARIO_SUMINISTROS"
INV_BA = "INVENTARIO_BARRA"

# ================================
# HELPERS
# ================================

def normalizar(texto):
    if not texto:
        return ""
    texto = texto.strip().upper()
    texto = unicodedata.normalize("NFKD", texto).encode("ASCII","ignore").decode()
    texto = " ".join(texto.split())
    return texto

def get_header_map(ws):
    header_row = ws.row_values(3)
    return {normalizar(name): idx for idx, name in enumerate(header_row, start=1)}

def get_dest_sheet(area):
    hojas = {ws.title.upper(): ws for ws in doc.worksheets()}
    mapa = {
        "COCINA": INV_CO.upper(),
        "CONSUMIBLE": INV_SU.upper(),
        "BARRA": INV_BA.upper()
    }
    target = mapa.get(area.upper())
    if target in hojas:
        return hojas[target]
    st.error("❌ No se encontró hoja del área")
    st.stop()

def col_letter(n):
    s = ""
    while n > 0:
        n, r = divmod(n-1, 26)
        s = chr(r+65) + s
    return s

# ================================
# CARGAR BD_productos
# ================================

@st.cache_data(show_spinner=False)
def get_bd():
    ws = doc.worksheet(BD_TAB)
    raw = ws.get_all_values(value_render_option="UNFORMATTED_VALUE")

    headers = [h.strip() for h in raw[0]]
    df = pd.DataFrame(raw[1:], columns=headers)
    df.columns = df.columns.str.upper().str.strip()
    return df

df = get_bd()

# ================================
# UI
# ================================

st.title("📦 Sistema de Inventario Diario – Restaurante")

fecha_inv = st.date_input("Fecha inventario:", value=date.today())
fecha_str = fecha_inv.strftime("%d-%m-%Y")

areas = sorted([a for a in df["ÁREA"].unique() if a.upper()!="GASTO"])
area = st.selectbox("Área:", areas)

df_area = df[df["ÁREA"]==area]

# ✅ detectar columna categoria automáticamente
col_categoria = next((c for c in df.columns if "CATEG" in c.upper()), None)

categorias = sorted(df_area[col_categoria].unique())
categoria = st.selectbox("Categoría:", ["TODOS"] + categorias)

if categoria!="TODOS":
    df_cat = df_area[df_area[col_categoria]==categoria]
else:
    df_cat = df_area

# ✅ detectar subfamilia
col_subfam = next((c for c in df.columns if "SUB" in c.upper()), None)

subfams = sorted(df_cat[col_subfam].unique())
subfam = st.selectbox("Sub familia:", ["TODOS"] + subfams)

if subfam!="TODOS":
    df_sf = df_cat[df_cat[col_subfam]==subfam]
else:
    df_sf = df_cat

# ✅ detectar PRODUCTO GENERICO
col_prod_bd = next((c for c in df.columns if "PRODUCTO GENER" in c.upper()), None)

productos = sorted(df_sf[col_prod_bd].unique())
prod = st.selectbox("Producto:", ["TODOS"] + productos)

if prod=="TODOS":
    productos_sel = productos
else:
    productos_sel = [prod]

tabla = pd.DataFrame({
    "PRODUCTO": productos_sel,
    "CANTIDAD CERRADO": [0.0]*len(productos_sel),
    "CANTIDAD ABIERTO": [0.0]*len(productos_sel)
})

tabla_editada = st.data_editor(
    tabla,
    num_rows="fixed",
    use_container_width=True
)

# ================================
# DETECCIÓN COLUMNAS HOJA DESTINO
# ================================

ws_dest = get_dest_sheet(area)
header_map = get_header_map(ws_dest)

col_prod    = next((v for k,v in header_map.items() if "PRODUCTO" in k),None)
col_cerrado = next((v for k,v in header_map.items() if "CERRADO" in k),None)
col_abierto = next((v for k,v in header_map.items() if "ABIERTO" in k),None)
col_fecha   = next((v for k,v in header_map.items() if "FECHA" in k),None)

# ================================
# GUARDAR
# ================================

def guardar():
    updates = []

    productos_sheet = ws_dest.col_values(col_prod)

    for _, row in tabla_editada.iterrows():
        nombre = row["PRODUCTO"].strip().upper()

        for idx in range(3,len(productos_sheet)):
            if str(productos_sheet[idx]).strip().upper()==nombre:
                fila = idx+1
                break
        else:
            continue

        if col_cerrado:
            updates.append({
                "range": f"{ws_dest.title}!{col_letter(col_cerrado)}{fila}",
                "values": [[row["CANTIDAD CERRADO"]]]
            })
        if col_abierto:
            updates.append({
                "range": f"{ws_dest.title}!{col_letter(col_abierto)}{fila}",
                "values": [[row["CANTIDAD ABIERTO"]]]
            })
        if col_fecha:
            updates.append({
                "range": f"{ws_dest.title}!{col_letter(col_fecha)}{fila}",
                "values": [[fecha_str]]
            })

    if updates:
        doc.batch_update({
            "value_input_option":"USER_ENTERED",
            "data":updates
        })
        return True
    return False

# ================================
# RESET
# ================================

def reset():
    products_sheet = ws_dest.col_values(col_prod)
    updates=[]
    for idx in range(3,len(products_sheet)):
        fila = idx+1
        if col_cerrado:
            updates.append({"range":f"{ws_dest.title}!{col_letter(col_cerrado)}{fila}","values":[[0]]})
        if col_abierto:
            updates.append({"range":f"{ws_dest.title}!{col_letter(col_abierto)}{fila}","values":[[0]]})
        if col_fecha:
            updates.append({"range":f"{ws_dest.title}!{col_letter(col_fecha)}{fila}","values":[[""]]})

    if updates:
        doc.batch_update({
            "value_input_option":"USER_ENTERED",
            "data":updates
        })

# ================================
# BOTONES
# ================================

col1,col2 = st.columns(2)

with col1:
    if st.button("💾 Guardar inventario"):
        if guardar():
            st.success("✅ Guardado")

with col2:
    if st.button("🧹 Reset inventario"):
        reset()
        st.success("✅ Reset realizado")


