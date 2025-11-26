import streamlit as st
import pandas as pd
import gspread
from datetime import date
from google.oauth2.service_account import Credentials

# =========================================================
#  CONFIG GOOGLE SHEETS
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
# HOJAS / CONFIG
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
# BASE DE DATOS PRINCIPAL
# =========================================================

@st.cache_data(show_spinner=False)
def load_bd():
    ws = doc.worksheet(BD_TAB)
    raw = ws.get_all_values(value_render_option="UNFORMATTED_VALUE")
    headers = [h.strip() for h in raw[0]]
    df = pd.DataFrame(raw[1:], columns=headers)

    df.columns = df.columns.str.upper().str.strip()

    numeric_cols = ["PRECIO NETO", "COSTO X UNIDAD", "CANTIDAD DE UNIDAD DE MEDIDA"]
    for col in numeric_cols:
        if col in df.columns:
            df[col] = (
                df[col]
                .astype(str)
                .str.replace(",", "")
            )
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.0)

    return df

df = load_bd()

# =========================================================
# FUNCIONES AUXILIARES GOOGLE SHEETS
# =========================================================

def colletter(n: int) -> str:
    s = ""
    while n > 0:
        n, r = divmod(n - 1, 26)
        s = chr(r + 65) + s
    return s


def get_sheet(area: str):
    area_up = area.upper()
    hojas = {ws.title.upper(): ws for ws in doc.worksheets()}

    if area_up == "COCINA":
        return hojas.get(INV_CO.upper())
    if area_up in ("CONSUMIBLE", "SUMINISTROS"):
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


def safe_float(x):
    try:
        if x in ["", None, "None"]:
            return 0.0
        return float(x)
    except Exception:
        return 0.0

# =========================================================
# UI
# =========================================================

st.title("📦 Sistema Inventario Batanga")

# 🔶 Advertencia grande al inicio
st.warning(
    """
⚠ **Atención al registrar inventario**

- Verifique que las *unidades* (CERRADO y ABIERTO) se ingresen correctamente.  
- El botón **RESET** borra **TODOS los datos del área seleccionada**, además del comentario en la celda C3.  
- Antes de guardar, revise que los valores de **VALOR INVENTARIO (Vista Previa)** sean razonables.

Esta acción no se puede deshacer.
""",
    icon="⚠",
)

# Fecha de inventario
fecha = st.date_input("Fecha de inventario:", value=date.today())
fecha_str = fecha.strftime("%d-%m-%Y")

st.markdown("### Selección de productos")

# ========= FILTROS =========

areas = sorted([x for x in df["ÁREA"].unique() if str(x).upper() != "GASTO"])
area = st.selectbox("Área:", areas)

df_area = df[df["ÁREA"] == area]

categoria = st.selectbox("Categoría:", sorted(df_area["CATEGORIA"].unique()))
df_cat = df_area[df_area["CATEGORIA"] == categoria]

subfams = ["TODOS"] + sorted(df_cat["SUB FAMILIA"].unique())
subfam = st.selectbox("Subfamilia:", subfams)

if subfam == "TODOS":
    df_sf = df_cat
else:
    df_sf = df_cat[df_cat["SUB FAMILIA"] == subfam]

prods = ["TODOS"] + sorted(df_sf["PRODUCTO GENÉRICO"].unique())
prod_sel = st.selectbox("Producto específico:", prods)

if prod_sel == "TODOS":
    df_sel = df_sf
else:
    df_sel = df_sf[df_sf["PRODUCTO GENÉRICO"] == prod_sel]

if df_sel.empty:
    st.info("No hay productos con los filtros seleccionados.")
    st.stop()

# =========================================================
# TABLA EDITABLE (sin carrito / sin memoria)
# =========================================================

st.subheader("Ingresar inventario")

base = {
    "PRODUCTO": df_sel["PRODUCTO GENÉRICO"].values,
    "UNIDAD": df_sel["UNIDAD RECETA"].values,
    "MEDIDA": df_sel["CANTIDAD DE UNIDAD DE MEDIDA"].values,
    "CERRADO": [0.0] * len(df_sel),
    "ABIERTO(PESO)": [0.0] * len(df_sel),
}

if area.upper() == "BARRA":
    base["BOTELLAS_ABIERTAS"] = [0.0] * len(df_sel)
else:
    base["BOTELLAS_ABIERTAS"] = [""] * len(df_sel)

tabla = pd.DataFrame(base)

df_edit = st.data_editor(
    tabla,
    use_container_width=True,
    disabled=["PRODUCTO", "UNIDAD", "MEDIDA"],
)

# =========================================================
# VISTA PREVIA
# =========================================================

st.subheader("Vista previa")

merge_cols = ["PRODUCTO GENÉRICO", "PRECIO NETO", "COSTO X UNIDAD"]
merge = df_sel[merge_cols].rename(columns={"PRODUCTO GENÉRICO": "PRODUCTO"})

prev = df_edit.merge(merge, on="PRODUCTO", how="left")

prev["VALOR INVENTARIO"] = (
    safe_float(prev["PRECIO NETO"]) * safe_float(prev["CERRADO"])
    + safe_float(prev["COSTO X UNIDAD"]) * safe_float(prev["ABIERTO(PESO)"])
)
prev["VALOR INVENTARIO"] = prev["VALOR INVENTARIO"].round(2)

filtro = (prev["CERRADO"] != 0) | (prev["ABIERTO(PESO)"] != 0)
if area.upper() == "BARRA":
    filtro |= (prev["BOTELLAS_ABIERTAS"] != 0)

prev_filtrado = prev[filtro]

cols = ["PRODUCTO", "CERRADO", "ABIERTO(PESO)"]
if area.upper() == "BARRA":
    cols.append("BOTELLAS_ABIERTAS")
cols.append("VALOR INVENTARIO")

if not prev_filtrado.empty:
    st.dataframe(prev_filtrado[cols], use_container_width=True)
else:
    st.info("No hay productos con valores distintos de 0 para mostrar en la vista previa.")

# =========================================================
# CONFIG SHEET DESTINO
# =========================================================

ws = get_sheet(area)
if ws is None:
    st.error(f"No se encontró hoja destino para el área '{area}'.")
    st.stop()

headers = get_headers(ws)

col_prod = headers.get("PRODUCTO GENÉRICO")
if col_prod is None:
    st.error("No se encontró la columna 'PRODUCTO GENÉRICO' en la hoja de inventario.")
    st.stop()

rows_map = get_rows(ws, col_prod)

col_cerrado = headers.get("CANTIDAD CERRADO")
col_abierto = headers.get("CANTIDAD ABIERTO (PESO)")
col_botellas = headers.get("CANTIDAD BOTELLAS ABIERTAS")
col_fecha = headers.get("FECHA")
col_valor = headers.get("VALOR INVENTARIO")

# =========================================================
# GUARDAR EN GOOGLE SHEETS
# =========================================================

def guardar_inventario():
    updates = []

    for _, r in prev_filtrado.iterrows():
        prod = str(r["PRODUCTO"]).strip().upper()
        if prod not in rows_map:
            continue

        row_idx = rows_map[prod]

        if col_cerrado:
            updates.append({
                "range": f"{colletter(col_cerrado)}{row_idx}",
                "values": [[safe_float(r["CERRADO"])]],
            })

        if col_abierto:
            updates.append({
                "range": f"{colletter(col_abierto)}{row_idx}",
                "values": [[safe_float(r["ABIERTO(PESO)"])]],
            })

        if area.upper() == "BARRA" and col_botellas:
            updates.append({
                "range": f"{colletter(col_botellas)}{row_idx}",
                "values": [[safe_float(r["BOTELLAS_ABIERTAS"])]],
            })

        if col_fecha:
            updates.append({
                "range": f"{colletter(col_fecha)}{row_idx}",
                "values": [[fecha_str]],
            })

    if updates:
        ws.batch_update(updates)

# =========================================================
# RESET INVENTARIO (incluye comentario C3)
# =========================================================

def reset_inventario():
    updates = []

    for row_idx in rows_map.values():
        if col_cerrado:
            updates.append({
                "range": f"{colletter(col_cerrado)}{row_idx}",
                "values": [[0]],
            })
        if col_abierto:
            updates.append({
                "range": f"{colletter(col_abierto)}{row_idx}",
                "values": [[0]],
            })
        if col_botellas:
            updates.append({
                "range": f"{colletter(col_botellas)}{row_idx}",
                "values": [[0]],
            })
        if col_valor:
            updates.append({
                "range": f"{colletter(col_valor)}{row_idx}",
                "values": [[0]],
            })
        if col_fecha:
            updates.append({
                "range": f"{colletter(col_fecha)}{row_idx}",
                "values": [[""]],
            })

    # Limpiar comentario en C3
    updates.append({"range": "C3", "values": [[""]]})

    if updates:
        ws.batch_update(updates)

# =========================================================
# COMENTARIO EN C3
# =========================================================

st.subheader("Comentario general del inventario")

comentario = st.text_area("Comentario (se guarda en la celda C3 de la hoja):", key="comentario_texto")

if st.button("💬 Guardar comentario en C3"):
    try:
        ws.update("C3", [[comentario]])
        st.success("✅ Comentario guardado en C3.")
    except Exception as e:
        st.error(f"Error al guardar el comentario en C3: {e}")

# =========================================================
# BOTONES GUARDAR / RESET CON CONFIRMACIÓN
# =========================================================

col1, col2 = st.columns(2)

with col1:
    if st.button("💾 Guardar inventario en Google Sheets"):
        guardar_inventario()
        st.success("✅ Inventario guardado en la hoja de Google Sheets.")

with col2:
    if st.button("🧹 Resetear inventario y comentario"):
        st.session_state["confirm_reset"] = True

if st.session_state["confirm_reset"]:
    st.error(
        "⚠ ¿Seguro que quieres RESETear **TODAS** las cantidades de inventario "
        "del área actual y borrar el comentario en C3?",
        icon="⚠",
    )
    c1, c2 = st.columns(2)
    with c1:
        if st.button("✅ Sí, resetear ahora"):
            reset_inventario()
            st.success("✅ Inventario y comentario reseteados.")
            st.session_state["confirm_reset"] = False
    with c2:
        if st.button("❌ Cancelar"):
            st.info("Operación cancelada. No se modificó nada.")
            st.session_state["confirm_reset"] = False
