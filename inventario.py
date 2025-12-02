import streamlit as st
import pandas as pd
import gspread
from datetime import date
from google.oauth2.service_account import Credentials

# =========================================================
# CONFIG GOOGLE SHEETS
# =========================================================

scope = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

DOC_NAME = "INVENTARIO BATANGA CIERRE FORM"

service_info = st.secrets["google_service_account"]
credentials = Credentials.from_service_account_info(service_info, scopes=scope)
client = gspread.authorize(credentials)

@st.cache_resource(show_spinner=False)
def get_doc():
    return client.open(DOC_NAME)

doc = get_doc()

# =========================================================
# HOJAS / CONFIG GENERAL
# =========================================================

INV_CO = "INVENTARIO_COCINA"
INV_SU = "INVENTARIO_SUMINISTROS"
INV_BA = "INVENTARIO_BARRA"

HEADER_ROW = 4
DATA_START = 5

if "confirm_reset" not in st.session_state:
    st.session_state["confirm_reset"] = False


# =========================================================
# FUNCIONES GSPREAD
# =========================================================

def colletter(n: int) -> str:
    s = ""
    while n > 0:
        n, r = divmod(n - 1, 26)
        s = chr(r + 65) + s
    return s

def get_sheet(area: str):
    hojas = {ws.title.upper(): ws for ws in doc.worksheets()}
    area_up = area.upper()

    if area_up == "COCINA":
        return hojas.get(INV_CO.upper())
    if area_up in ("SUMINISTROS", "CONSUMIBLE"):
        return hojas.get(INV_SU.upper())
    if area_up == "BARRA":
        return hojas.get(INV_BA.upper())

    st.error(f"Área inválida: {area}")
    st.stop()

@st.cache_data(show_spinner=False)
def load_area_products(area):
    ws = get_sheet(area)
    raw = ws.get_all_values(value_render_option="UNFORMATTED_VALUE")

    headers = raw[HEADER_ROW - 1]
    data = raw[DATA_START - 1:]

    df = pd.DataFrame(data, columns=headers)
    df.columns = df.columns.str.upper().str.strip()
    df = df[df["PRODUCTO GENÉRICO"].notna()]
    df = df[df["PRODUCTO GENÉRICO"].astype(str).str.strip() != ""]
    return df

def get_headers(ws) -> dict:
    header_row = ws.row_values(HEADER_ROW)
    return {
        str(h).strip().upper(): idx
        for idx, h in enumerate(header_row, start=1)
        if str(h).strip() != ""
    }

def get_rows(ws, col_idx_producto: int) -> dict:
    vals = ws.col_values(col_idx_producto)
    mapping = {}
    for i in range(DATA_START, len(vals) + 1):
        val = str(vals[i - 1]).strip()
        if val:
            mapping[val.upper()] = i
    return mapping


# =========================================================
# UI PRINCIPAL
# =========================================================

st.title("📦 Inventario Diario — Batanga")

st.warning(
    "⚠ Validar cantidades ANTES de guardar.\n\n"
    "⚠ El botón RESET borra cantidades del área actual + comentario del inventario.\n"
    "⚠ El valor final lo calcula automáticamente Google Sheets."
)

fecha = st.date_input("Fecha de inventario:", value=date.today())
fecha_str = fecha.strftime("%d-%m-%Y")

st.markdown("### Selección de productos")

# =========================================================
# FILTROS DESDE HOJA REAL
# =========================================================

areas = ["COCINA", "SUMINISTROS", "BARRA"]
area = st.selectbox("Área:", areas)

df_area = load_area_products(area)

# categoría
if "CATEGORIA" in df_area.columns:
    categorias = ["TODOS"] + sorted(df_area["CATEGORIA"].dropna().unique())
    categoria = st.selectbox("Categoría:", categorias)
    df_filt = df_area if categoria == "TODOS" else df_area[df_area["CATEGORIA"] == categoria]
else:
    df_filt = df_area

# subfamilia
if "SUB FAMILIA" in df_filt.columns:
    subfams = ["TODOS"] + sorted(df_filt["SUB FAMILIA"].dropna().unique())
    subfam = st.selectbox("Subfamilia:", subfams)
    df_filt = df_filt if subfam == "TODOS" else df_filt[df_filt["SUB FAMILIA"] == subfam]

# productos
prods = ["TODOS"] + sorted(df_filt["PRODUCTO GENÉRICO"].dropna().unique())
prod_sel = st.selectbox("Producto específico:", prods)

df_sel = df_filt if prod_sel == "TODOS" else df_filt[df_filt["PRODUCTO GENÉRICO"] == prod_sel]

if df_sel.empty:
    st.info("No hay productos con los filtros actuales.")
    st.stop()


# =========================================================
# TABLA EDITABLE
# =========================================================

st.subheader("Ingresar inventario")

tabla = {
    "PRODUCTO": df_sel["PRODUCTO GENÉRICO"].tolist(),
    "UNIDAD": df_sel["UNIDAD RECETA"].tolist(),
    "MEDIDA": df_sel["CANTIDAD DE UNIDAD DE MEDIDA"].tolist(),
    "CERRADO": [0.0] * len(df_sel),
    "ABIERTO(PESO)": [0.0] * len(df_sel),
}

if area.upper() == "BARRA":
    tabla["BOTELLAS_ABIERTAS"] = [0.0] * len(df_sel)
else:
    tabla["BOTELLAS_ABIERTAS"] = [""] * len(df_sel)

df_edit = st.data_editor(
    pd.DataFrame(tabla),
    use_container_width=True,
    disabled=["PRODUCTO", "UNIDAD", "MEDIDA"],
)

# =========================================================
# VISTA PREVIA GLOBAL
# =========================================================

st.subheader("Vista previa (global)")

if "preview_global" not in st.session_state:
    st.session_state["preview_global"] = pd.DataFrame(
        columns=["PRODUCTO", "CERRADO", "ABIERTO(PESO)", "BOTELLAS_ABIERTAS"]
    )

mask = (df_edit["CERRADO"] != 0) | (df_edit["ABIERTO(PESO)"] != 0)
if area.upper() == "BARRA":
    mask |= (df_edit["BOTELLAS_ABIERTAS"] != 0)

entrada = df_edit[mask].copy()

if not entrada.empty:
    prev = st.session_state["preview_global"]
    prev = prev[~prev["PRODUCTO"].isin(entrada["PRODUCTO"])]
    prev = pd.concat([prev, entrada], ignore_index=True)
    st.session_state["preview_global"] = prev

prev = st.session_state["preview_global"].copy()

if not prev.empty:
    st.dataframe(prev, use_container_width=True)
    st.session_state["vista_global"] = prev.copy()
else:
    st.info("No hay productos registrados todavía.")


# =========================================================
# GUARDAR INVENTARIO
# =========================================================

def guardar_desde_preview():

    if "vista_global" not in st.session_state or st.session_state["vista_global"].empty:
        st.warning("No hay datos para guardar.")
        return

    tabla = st.session_state["vista_global"]
    ws = get_sheet(area)
    headers = get_headers(ws)

    col_prod = headers.get("PRODUCTO GENÉRICO")
    col_cer = headers.get("CANTIDAD CERRADO")
    col_abi = headers.get("CANTIDAD ABIERTO (PESO)")
    col_bot = headers.get("CANTIDAD BOTELLAS ABIERTAS")
    col_fecha = headers.get("FECHA")

    rows = get_rows(ws, col_prod)

    updates = []

    def to_num(v):
        try:
            return float(v)
        except:
            return 0

    for _, r in tabla.iterrows():
        prod = r["PRODUCTO"].upper()
        if prod not in rows:
            continue

        row = rows[prod]

        cerrado = to_num(r["CERRADO"])
        abierto = to_num(r["ABIERTO(PESO)"])
        botellas = to_num(r.get("BOTELLAS_ABIERTAS", 0))

        if col_cer:
            updates.append({"range": f"{colletter(col_cer)}{row}", "values": [[cerrado]]})
        if col_abi:
            updates.append({"range": f"{colletter(col_abi)}{row}", "values": [[abierto]]})
        if area.upper() == "BARRA" and col_bot:
            updates.append({"range": f"{colletter(col_bot)}{row}", "values": [[botellas]]})
        if col_fecha:
            updates.append({"range": f"{colletter(col_fecha)}{row}", "values": [[fecha_str]]})

    ws.batch_update(updates)
    st.success("Inventario guardado ✔")


# =========================================================
# RESET
# =========================================================

def reset_inventario():

    ws = get_sheet(area)
    headers = get_headers(ws)

    col_prod = headers.get("PRODUCTO GENÉRICO")
    rows_map = get_rows(ws, col_prod)

    updates = []

    for row in rows_map.values():
        for campo in ["CANTIDAD CERRADO", "CANTIDAD ABIERTO (PESO)", "CANTIDAD BOTELLAS ABIERTAS"]:
            col = headers.get(campo)
            if col:
                updates.append({"range": f"{colletter(col)}{row}", "values": [[0]]})

        col_fecha = headers.get("FECHA")
        if col_fecha:
            updates.append({"range": f"{colletter(col_fecha)}{row}", "values": [[""]]})

    updates.append({"range": "C3", "values": [[""]]})
    ws.batch_update(updates)

    if "preview_global" in st.session_state:
        productos_area = set(rows_map.keys())
        st.session_state["preview_global"] = st.session_state["preview_global"][
            ~st.session_state["preview_global"]["PRODUCTO"].str.upper().isin(productos_area)
        ]

    st.session_state.pop("comentario_texto", None)
    st.success("Área reseteada correctamente ✔")


# =========================================================
# COMENTARIO
# =========================================================

st.subheader("Comentario general")

comentario = st.text_area("Comentario (C3)", key="comentario_texto")

if st.button("💬 Guardar comentario"):
    ws = get_sheet(area)
    ws.update("C3", [[comentario]])
    st.success("Comentario guardado ✔")


# =========================================================
# BOTONES
# =========================================================

st.write("---")
c1, c2 = st.columns(2)

with c1:
    if st.button("💾 Guardar Inventario"):
        guardar_desde_preview()

with c2:
    if st.button("🧹 Resetear área"):
        st.session_state["confirm_reset"] = True

if st.session_state.get("confirm_reset", False):
    st.error("⚠ Esto borrará TODO el inventario del área seleccionada.")
    a, b = st.columns(2)

    if a.button("✔ Confirmar"):
        reset_inventario()
        st.session_state["confirm_reset"] = False

    if b.button("✖ Cancelar"):
        st.session_state["confirm_reset"] = False
