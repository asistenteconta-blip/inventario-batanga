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
            df[c] = (
                df[c]
                .astype(str)
                .str.replace(",", "")
            )
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
    "⚠ El botón RESET borra cantidades del área actual + el comentario del inventario, este cambio es irreversible.\n"
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
    st.info("No hay productos con los filtros actuales.")
    st.stop()


# =========================================================
# 🔥 TABLA EDITABLE CON MEMORIA SIN DOBLE ESCRITURA 100% REAL
# =========================================================

tabla_key  = f"INV|{area}|{categoria}|{subfam}|{prod_sel}"

# 1) Crear tabla inicial solo si no existe
if tabla_key not in st.session_state:
    st.session_state[tabla_key] = pd.DataFrame({
        "PRODUCTO": df_sel["PRODUCTO GENÉRICO"].tolist(),
        "UNIDAD": df_sel["UNIDAD RECETA"].tolist(),
        "MEDIDA": df_sel["CANTIDAD DE UNIDAD DE MEDIDA"].tolist(),
        "CERRADO": [0.0]*len(df_sel),
        "ABIERTO(PESO)": [0.0]*len(df_sel),
        "BOTELLAS_ABIERTAS": [0.0 if area.upper()=="BARRA" else ""]*len(df_sel)
    })

# 2) Crear buffer temporal para edición
if f"BUFFER_{tabla_key}" not in st.session_state:
    st.session_state[f"BUFFER_{tabla_key}"] = st.session_state[tabla_key].copy()


# ======== SYNCH — CLAVE PARA QUE NO SE BORRE LA 1ERA ESCRITURA ========
def sync_memoria():
    st.session_state[tabla_key] = st.session_state[f"BUFFER_{tabla_key}"].copy()


# ======== EDITOR FINAL =========
st.subheader("Ingresar inventario")

st.data_editor(
    st.session_state[f"BUFFER_{tabla_key}"],
    key=f"EDIT_{tabla_key}",
    use_container_width=True,
    disabled=["PRODUCTO","UNIDAD","MEDIDA"],
    on_change=sync_memoria    # ← 🔥 hace que la primera edición se guarde
)

# Garantiza sincronización en cada cambio de filtros sin borrar datos
sync_memoria()  
df_edit = st.session_state[tabla_key].copy()  # ← ahora es estable


# =========================================================
# VISTA PREVIA
# =========================================================

st.subheader("Vista previa")

merge_cols = ["PRODUCTO GENÉRICO", "PRECIO NETO", "COSTO X UNIDAD"]
merge = df_sel[merge_cols].rename(columns={"PRODUCTO GENÉRICO": "PRODUCTO"})

prev = df_edit.merge(merge, on="PRODUCTO", how="left")

prev["VALOR INVENTARIO (PREVIO)"] = (
    prev["PRECIO NETO"] * prev["CERRADO"]
    + prev["COSTO X UNIDAD"] * prev["ABIERTO(PESO)"]
)
prev["VALOR INVENTARIO (PREVIO)"] = prev["VALOR INVENTARIO (PREVIO)"].round(2)

filtro = (prev["CERRADO"] != 0) | (prev["ABIERTO(PESO)"] != 0)
if area.upper() == "BARRA":
    filtro |= (prev["BOTELLAS_ABIERTAS"] != 0)

prev_filtrado = prev[filtro]

cols = ["PRODUCTO", "CERRADO", "ABIERTO(PESO)"]
if area.upper() == "BARRA":
    cols.append("BOTELLAS_ABIERTAS")
cols.append("VALOR INVENTARIO (PREVIO)")

if not prev_filtrado.empty:
    st.dataframe(prev_filtrado[cols], use_container_width=True)
else:
    st.info("No hay productos con valores distintos a 0 para mostrar en la vista previa.")


# =========================================================
# PREPARAR GOOGLE SHEETS DESTINO
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
# col_valor = headers.get("VALOR INVENTARIO")  # NO lo tocamos para no borrar fórmula


# =========================================================
# GUARDAR EN GOOGLE SHEETS (NO TOCA FÓRMULA)
# =========================================================

def guardar_inventario():
    updates = []

    for _, r in prev_filtrado.iterrows():
        prod = str(r["PRODUCTO"]).strip().upper()
        if prod not in rows_map:
            continue

        row_idx = rows_map[prod]

        # CERRADO
        if col_cerrado:
            val_cerrado = r["CERRADO"] if r["CERRADO"] not in ["", None] else 0
            updates.append({
                "range": f"{colletter(col_cerrado)}{row_idx}",
                "values": [[float(val_cerrado)]],
            })

        # ABIERTO PESO (aquí estaba el error)
        if col_abierto:
            val_abierto = r["ABIERTO(PESO)"] if r["ABIERTO(PESO)"] not in ["", None] else 0
            updates.append({
                "range": f"{colletter(col_abierto)}{row_idx}",
                "values": [[float(val_abierto)]],
            })

        # BOTELLAS ABAERTAS solo barra
        if area.upper()=="BARRA" and col_botellas:
            vb = r.get("BOTELLAS_ABIERTAS",0)
            try: vb = float(vb) if vb not in ["",None] else 0
            except: vb = 0
            updates.append({
                "range": f"{colletter(col_botellas)}{row_idx}",
                "values":[[vb]],
            })

        # FECHA
        if col_fecha:
            updates.append({
                "range": f"{colletter(col_fecha)}{row_idx}",
                "values": [[fecha_str]]
            })

    if updates:
        ws.batch_update(updates)



# =========================================================
# RESET INVENTARIO (AREA ACTUAL) + C3
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
        if col_fecha:
            updates.append({
                "range": f"{colletter(col_fecha)}{row_idx}",
                "values": [[""]],
            })

    # Limpiar comentario en C3
    updates.append({"range": "C3", "values": [[""]]})

    if updates:
        ws.batch_update(updates)

    # Limpiar tablas en memoria para ESTA área
    keys_to_clear = [
        k for k in list(st.session_state.keys())
        if k.startswith("tabla|"+area+"|")
    ]
    for k in keys_to_clear:
        del st.session_state[k]

    # Limpiar comentario en UI
    st.session_state.pop("comentario_texto", None)


# =========================================================
# COMENTARIO EN C3
# =========================================================

st.subheader("Comentario general del inventario")

comentario = st.text_area(
    "Comentario (se guarda en la celda C3 de la hoja del área):",
    key="comentario_texto"
)

if st.button("💬 Guardar comentario"):
    try:
        ws.update("C3", [[comentario]])
        st.success("✅ Comentario guardado.")
    except Exception as e:
        st.error(f"Error al guardar el comentario: {e}")


# =========================================================
# BOTONES GUARDAR / RESET CON CONFIRMACIÓN
# =========================================================

col1, col2 = st.columns(2)

with col1:
    if st.button("💾 Guardar inventario en Google Sheets"):
        guardar_inventario()
        st.success("✅ Inventario guardado en la hoja de Google Sheets.")

with col2:
    if st.button("🧹 Resetear inventario del área y comentario"):
        st.session_state["confirm_reset"] = True

if st.session_state["confirm_reset"]:
    st.error(
        "⚠ ¿Seguro que quieres resetear TODAS las cantidades de inventario "
        f"del área **{area}** y borrar el comentario?\n\n"
        "Esta acción no se puede deshacer.",
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



















