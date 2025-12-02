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

DOC_NAME = "Copia de MACHOTE INV BATANGA DDMMAAAA  ACT25"

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

BD_TAB = "BD_productos"
INV_CO = "INVENTARIO_COCINA"
INV_SU = "INVENTARIO_SUMINISTROS"
INV_BA = "INVENTARIO_BARRA"

HEADER_ROW = 4
DATA_START = 5

if "confirm_reset" not in st.session_state:
    st.session_state["confirm_reset"] = False

# =========================================================
# CARGA BASE DE PRODUCTOS
# =========================================================

@st.cache_data(show_spinner=False)
def load_bd():
    ws = doc.worksheet(BD_TAB)
    raw = ws.get_all_values(value_render_option="UNFORMATTED_VALUE")
    df = pd.DataFrame(raw[1:], columns=raw[0])

    df.columns = df.columns.str.upper().str.strip()

    for c in ["PRECIO NETO", "COSTO X UNIDAD", "CANTIDAD DE UNIDAD DE MEDIDA"]:
        if c in df.columns:
            df[c] = df[c].astype(str).str.replace(",", "")
            df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0.0)

    return df

df = load_bd()

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

# ================= FILTROS =================

areas = sorted([a for a in df["ÁREA"].unique() if str(a).upper() != "GASTO"])
area = st.selectbox("Área:", areas)

df_area = df[df["ÁREA"] == area]

categoria = st.selectbox("Categoría:", sorted(df_area["CATEGORIA"].unique()))
df_cat = df_area[df_area["CATEGORIA"] == categoria]

subfams = ["TODOS"] + sorted(df_cat["SUB FAMILIA"].unique())
subfam = st.selectbox("Subfamilia:", subfams)

df_sf = df_cat if subfam == "TODOS" else df_cat[df_cat["SUB FAMILIA"] == subfam]

prods = ["TODOS"] + sorted(df_sf["PRODUCTO GENÉRICO"].unique())
prod_sel = st.selectbox("Producto específico:", prods)

df_sel = df_sf if prod_sel == "TODOS" else df_sf[df_sf["PRODUCTO GENÉRICO"] == prod_sel]

if df_sel.empty:
    st.info("No hay productos con los filtros actuales.")
    st.stop()


# =========================================================
# TABLA EDITABLE (SIN MEMORIA POR CATEGORÍA)
# =========================================================

st.subheader("Ingresar inventario (esta tabla se reinicia al cambiar filtros)")

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
    df_prec = df[["PRODUCTO GENÉRICO", "PRECIO NETO", "COSTO X UNIDAD"]]
    df_prec = df_prec.rename(columns={"PRODUCTO GENÉRICO": "PRODUCTO"})
    prev = prev.merge(df_prec, on="PRODUCTO", how="left")

    prev["VALOR INVENTARIO (PREVIO)"] = (
        prev["PRECIO NETO"].fillna(0) * prev["CERRADO"].fillna(0)
        + prev["COSTO X UNIDAD"].fillna(0) * prev["ABIERTO(PESO)"].fillna(0)
    )

    prev["VALOR INVENTARIO (PREVIO)"] = prev["VALOR INVENTARIO (PREVIO)"].round(2)

    st.dataframe(prev, use_container_width=True)

    # 🔥 FIX MÁS IMPORTANTE: guardar lista final para botón GUARDAR
    st.session_state["vista_global"] = prev.copy()

else:
    st.info("No hay productos registrados todavía.")

# =========================================================
# GUARDAR INVENTARIO
# =========================================================

def guardar_desde_preview():

    if "vista_global" not in st.session_state or st.session_state["vista_global"].empty:
        st.warning("No hay datos en la vista previa global para guardar.")
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
            if v in ["", None, "None"]:
                return 0
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
        if area.upper()=="BARRA" and col_bot:
            updates.append({"range": f"{colletter(col_bot)}{row}", "values": [[botellas]]})
        if col_fecha:
            updates.append({"range": f"{colletter(col_fecha)}{row}", "values": [[fecha_str]]})

    ws.batch_update(updates)
    st.success("Inventario guardado en Google Sheets ✔", icon="💾")


# =========================================================
# RESET
# =========================================================

def reset_inventario():

    ws = get_sheet(area)
    headers = get_headers(ws)

    col_prod = headers.get("PRODUCTO GENÉRICO")
    rows_map = get_rows(ws, col_prod)

    updates = []

    col_cer = headers.get("CANTIDAD CERRADO")
    col_abi = headers.get("CANTIDAD ABIERTO (PESO)")
    col_bot = headers.get("CANTIDAD BOTELLAS ABIERTAS")
    col_fecha = headers.get("FECHA")

    for row in rows_map.values():

        if col_cer:
            updates.append({"range": f"{colletter(col_cer)}{row}", "values": [[0]]})
        if col_abi:
            updates.append({"range": f"{colletter(col_abi)}{row}", "values": [[0]]})
        if col_bot:
            updates.append({"range": f"{colletter(col_bot)}{row}", "values": [[0]]})
        if col_fecha:
            updates.append({"range": f"{colletter(col_fecha)}{row}", "values": [[""]]})

    updates.append({"range": "C3", "values": [[""]]})  # Borra comentario

    ws.batch_update(updates)

    # Borrar vista previa SOLO de esta área
    if "preview_global" in st.session_state:
        pg = st.session_state["preview_global"]
        productos_area = set(rows_map.keys())
        st.session_state["preview_global"] = pg[
            ~pg["PRODUCTO"].str.upper().isin(productos_area)
        ]

    st.session_state.pop("comentario_texto", None)

# =========================================================
# COMENTARIO
# =========================================================

st.subheader("Comentario general del inventario")

comentario = st.text_area(
    "Comentario (se guarda en la celda C3):",
    key="comentario_texto"
)

if st.button("💬 Guardar comentario"):
    ws = get_sheet(area)
    ws.update("C3", [[comentario]])
    st.success("Comentario guardado ✔")

# =========================================================
# BOTONES
# =========================================================

st.write("---")
col1, col2 = st.columns(2)

with col1:
    if st.button("💾 Guardar Inventario en Google Sheets"):
        guardar_desde_preview()

with col2:
    if st.button("🧹 Resetear inventario del área y comentario"):
        st.session_state["confirm_reset"] = True

if st.session_state["confirm_reset"]:
    st.error(
        f"⚠ ¿Seguro que quieres resetear TODO el inventario del área {area} y borrar el comentario?\n\n"
        "Esta acción no se puede deshacer."
    )
    c1, c2 = st.columns(2)

    with c1:
        if st.button("✔ Sí, resetear ahora"):
            reset_inventario()
            st.success("Inventario y vista previa reseteados ✔")
            st.session_state["confirm_reset"] = False

    with c2:
        if st.button("✖ Cancelar"):
            st.session_state["confirm_reset"] = False
