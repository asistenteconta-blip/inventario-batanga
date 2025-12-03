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
# HOJAS
# =========================================================

INV_CO = "INVENTARIO_COCINA"
INV_SU = "INVENTARIO_SUMINISTROS"
INV_BA = "INVENTARIO_BARRA"

HEADER_ROW = 4
DATA_START = 5

if "confirm_reset" not in st.session_state:
    st.session_state["confirm_reset"] = False

# =========================================================
# FUNCIONES
# =========================================================

def colletter(n):
    s = ""
    while n > 0:
        n, r = divmod(n - 1, 26)
        s = chr(r + 65) + s
    return s

def safe_value(v):
    try:
        if pd.isna(v) or v == "":
            return 0
        return float(v)
    except:
        return 0

def get_sheet(area):
    hojas = {ws.title.upper(): ws for ws in doc.worksheets()}
    a = area.upper()
    if a == "COCINA": return hojas[INV_CO]
    if a in ["SUMINISTROS", "CONSUMIBLE"]: return hojas[INV_SU]
    if a == "BARRA": return hojas[INV_BA]
    st.error("Área inválida")
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

def get_headers(ws):
    header_row = ws.row_values(HEADER_ROW)
    return {str(h).strip().upper(): i for i, h in enumerate(header_row, start=1) if h}

def get_rows(ws, col):
    vals = ws.col_values(col)
    return {
        str(v).upper(): i
        for i, v in enumerate(vals, start=1)
        if i >= DATA_START and str(v).strip() != ""
    }

# =========================================================
# UI PRINCIPAL
# =========================================================

st.title("📦 Inventario Diario — Batanga")
st.warning("""
⚠ Verifica antes de guardar.
⚠ Reset borra todos los datos de Google Sheets del área actual.
⚠ Usa el botón de guardar comentario hasta terminar todo el inventario.
""")

fecha = st.date_input("Fecha:", date.today())
fecha_str = fecha.strftime("%d-%m-%Y")

areas = ["COCINA", "SUMINISTROS", "BARRA"]
area = st.selectbox("Área:", areas)

df_area = load_area_products(area)

# =========================================================
# FILTROS
# =========================================================

if "CATEGORIA" in df_area.columns:
    categorias = ["TODOS"] + sorted(df_area["CATEGORIA"].dropna().unique())
    categoria = st.selectbox("Categoría:", categorias)
    df_fil = df_area if categoria == "TODOS" else df_area[df_area["CATEGORIA"] == categoria]
else:
    df_fil = df_area

if "SUB FAMILIA" in df_fil.columns:
    subfams = ["TODOS"] + sorted(df_fil["SUB FAMILIA"].dropna().unique())
    subfam = st.selectbox("Subfamilia:", subfams)
    df_fil = df_fil if subfam == "TODOS" else df_fil[df_fil["SUB FAMILIA"] == subfam]

prods = ["TODOS"] + sorted(df_fil["PRODUCTO GENÉRICO"].dropna().unique())
prod_sel = st.selectbox("Producto:", prods)

df_sel = df_fil if prod_sel == "TODOS" else df_fil[df_fil["PRODUCTO GENÉRICO"] == prod_sel]

if df_sel.empty:
    st.info("No hay productos con los filtros.")
    st.stop()

# =========================================================
# TABLA EDITABLE (Entrada)
# =========================================================

tabla = {
    "PRODUCTO": df_sel["PRODUCTO GENÉRICO"].tolist(),
    "UNIDAD": df_sel["UNIDAD RECETA"].tolist(),
    "MEDIDA": df_sel["CANTIDAD DE UNIDAD DE MEDIDA"].tolist(),

    # INVISIBLES (solo para cálculos)
    "_PRECIO_NETO": pd.to_numeric(
        df_sel["PRECIO NETO"].astype(str).str.replace(",", ".", regex=False).str.strip(),
        errors="coerce"
    ).fillna(0).tolist(),

    "_COSTO_X_UNIDAD": pd.to_numeric(
        df_sel["COSTO X UNIDAD"].astype(str).str.replace(",", ".", regex=False).str.strip(),
        errors="coerce"
    ).fillna(0).tolist(),

    # EDITABLES
    "CERRADO": [0.0] * len(df_sel),
    "ABIERTO(PESO)": [0.0] * len(df_sel),
}

# BOTELLAS ABRITAS SOLO PARA BARRA
tabla["BOTELLAS_ABIERTAS"] = [0.0] * len(df_sel) if area == "BARRA" else [""] * len(df_sel)

df_tabla = pd.DataFrame(tabla)

# Convertir campos numéricos
for c in ["CERRADO", "ABIERTO(PESO)", "BOTELLAS_ABIERTAS"]:
    if c in df_tabla.columns:
        df_tabla[c] = pd.to_numeric(df_tabla[c], errors="coerce").fillna(0.0)

# Editor SOLO con las columnas visibles
columnas_visibles = ["PRODUCTO", "UNIDAD", "MEDIDA", "CERRADO", "ABIERTO(PESO)"]
if area == "BARRA":
    columnas_visibles.append("BOTELLAS_ABIERTAS")

df_edit = st.data_editor(
    df_tabla[columnas_visibles + ["_PRECIO_NETO", "_COSTO_X_UNIDAD"]],
    disabled=["PRODUCTO", "UNIDAD", "MEDIDA"],
    hide_index=True,
    use_container_width=True,
    column_config={
        "_PRECIO_NETO": st.column_config.NumberColumn(visible=False),
        "_COSTO_X_UNIDAD": st.column_config.NumberColumn(visible=False),
    }
)

# =========================================================
# CALCULO VALOR DE INVENTARIO
# =========================================================

df_edit["VALOR INVENTARIO"] = (
    df_edit["CERRADO"] * df_edit["_PRECIO_NETO"]
    + df_edit["ABIERTO(PESO)"] * df_edit["_COSTO_X_UNIDAD"]
)


# =========================================================
# CALCULO VALOR DE INVENTARIO
# =========================================================

df_edit["VALOR INVENTARIO"] = (
    df_edit["CERRADO"] * df_edit["PRECIO NETO"]
    + df_edit["ABIERTO(PESO)"] * df_edit["COSTO X UNIDAD"]
)

# =========================================================
# PREVIEW POR AREA
# =========================================================

if "preview_por_area" not in st.session_state:
    st.session_state["preview_por_area"] = {
        "COCINA": pd.DataFrame(),
        "SUMINISTROS": pd.DataFrame(),
        "BARRA": pd.DataFrame(),
    }

mask = (df_edit["CERRADO"] != 0) | (df_edit["ABIERTO(PESO)"] != 0)
if area == "BARRA":
    mask |= df_edit["BOTELLAS_ABIERTAS"] != 0

entrada = df_edit[mask].copy()

if not entrada.empty:
    prev = st.session_state["preview_por_area"][area]

    # Quitar items duplicados
    if not prev.empty:
        prev = prev[~prev["PRODUCTO"].isin(entrada["PRODUCTO"])]

    prev = pd.concat([prev, entrada], ignore_index=True)
    st.session_state["preview_por_area"][area] = prev

st.subheader("Vista previa")

prev = st.session_state["preview_por_area"][area]

# OCULTAR CAMPOS EN VISTA PREVIA - SIN ERRORES
ocultar_cols = ["UNIDAD", "MEDIDA", "PRECIO NETO", "COSTO X UNIDAD"]

if not prev.empty:
    prev_vista = prev.drop(columns=[c for c in ocultar_cols if c in prev.columns])
    st.dataframe(prev_vista, use_container_width=True)
else:
    st.info("Sin registros aún.")


# =========================================================
# GUARDAR A GOOGLE SHEETS
# =========================================================

def guardar():
    prev = st.session_state["preview_por_area"][area]
    if prev.empty:
        st.warning("No hay datos para guardar.")
        return

    ws = get_sheet(area)
    headers = get_headers(ws)
    col_prod = headers.get("PRODUCTO GENÉRICO")
    rows = get_rows(ws, col_prod)

    updates = []

    for _, r in prev.iterrows():
        prod = r["PRODUCTO"].upper()
        row = rows.get(prod)
        if not row:
            continue

        campos = [
            ("CERRADO", "CANTIDAD CERRADO"),
            ("ABIERTO(PESO)", "CANTIDAD ABIERTO (PESO)"),
            ("BOTELLAS_ABIERTAS", "CANTIDAD BOTELLAS ABIERTAS"),
        ]

        for campo, colname in campos:
            col = headers.get(colname)
            if col:
                updates.append({
                    "range": f"{colletter(col)}{row}",
                    "values": [[safe_value(r[campo])]]
                })

        col_fecha = headers.get("FECHA")
        if col_fecha:
            updates.append({
                "range": f"{colletter(col_fecha)}{row}",
                "values": [[fecha_str]]
            })

    ws.batch_update(updates)
    st.success("Inventario guardado ✔")

# =========================================================
# RESET + BORRAR COMENTARIO
# =========================================================

def resetear():
    ws = get_sheet(area)
    headers = get_headers(ws)
    rows = get_rows(ws, headers.get("PRODUCTO GENÉRICO"))

    updates = []
    # Reset de inventario
    for row in rows.values():
        for campo in ["CANTIDAD CERRADO", "CANTIDAD ABIERTO (PESO)", "CANTIDAD BOTELLAS ABIERTAS"]:
            col = headers.get(campo)
            if col:
                updates.append({"range": f"{colletter(col)}{row}", "values": [[0]]})

        col_f = headers.get("FECHA")
        if col_f:
            updates.append({"range": f"{colletter(col_f)}{row}", "values": [[""]]})

    # BORRAR COMENTARIO TAMBIÉN AQUÍ
    updates.append({"range": "C3", "values": [[""]]})

    ws.batch_update(updates)

    # Reset vista previa del área
    st.session_state["preview_por_area"][area] = pd.DataFrame()

    # Reset comentario en pantalla
    if "comentario" in st.session_state:
        st.session_state["comentario"] = ""

    st.success("Área reseteada ✔")


    # BORRAR COMENTARIO
    updates.append({"range": "C3", "values": [[""]]})

    ws.batch_update(updates)

    st.session_state["preview_por_area"][area] = pd.DataFrame()

    st.success("Área reseteada ✔")

# =========================================================
# BOTONES
# =========================================================

c1, c2 = st.columns(2)

if c1.button("💾 Guardar"):
    guardar()

if c2.button("🧹 Resetear"):
    st.session_state["confirm_reset"] = True

if st.session_state.get("confirm_reset", False):
    st.error("⚠ Esto borrará TODO el inventario del área actual.")
    a, b = st.columns(2)

    if a.button("✔ Confirmar"):
        resetear()
        st.session_state["confirm_reset"] = False

    if b.button("✖ Cancelar"):
        st.session_state["confirm_reset"] = False

# =========================================================
# COMENTARIO
# =========================================================

st.subheader("Comentario")
coment = st.text_area("Comentario general", key="comentario")

if st.button("💬 Guardar comentario"):
    ws = get_sheet(area)
    ws.update("C3", [[st.session_state["comentario"]]])
    st.success("Comentario guardado ✔")



