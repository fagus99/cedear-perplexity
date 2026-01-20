import streamlit as st
import pandas as pd
import re

# Configuración de la página
st.set_page_config(page_title="Calculadora de Arbitraje CEDEARs", layout="wide")

st.title("💹 Calculadora de Arbitraje y Tipo de Cambio Implícito")
st.markdown("""
Esta herramienta compara las cotizaciones de CEDEARs en Pesos y Dólares para calcular el tipo de cambio implícito (CCL/MEP Implícito).
""")

# --- FUNCIONES DE PROCESAMIENTO ---

def find_header_row(df):
    """Busca la fila que contiene la palabra 'Símbolo' para usarla como encabezado."""
    for idx, row in df.iterrows():
        # Buscamos en las primeras columnas texto que coincida
        if row.astype(str).str.contains("Símbolo", case=False).any():
            return idx
    return 0

def clean_price(val):
    """Convierte strings de precio (ej: 'ARS 1.400,50') a float."""
    if pd.isna(val) or str(val).strip() == '-':
        return None
    
    val_str = str(val)
    # Eliminar prefijos de moneda y espacios
    val_str = re.sub(r'(ARS|USD|\$)\s*', '', val_str, flags=re.IGNORECASE).strip()
    
    # Manejo de formato latino: 1.000,00 -> eliminar punto, reemplazar coma por punto
    # Pero primero asegurarnos que no sea un formato americano puro sin separadores de miles confusos
    if ',' in val_str and '.' in val_str:
        if val_str.find('.') < val_str.find(','): 
            # Caso 1.000,50
            val_str = val_str.replace('.', '').replace(',', '.')
        else:
            # Caso 1,000.50 (raro en estos archivos pero posible)
            val_str = val_str.replace(',', '')
    elif ',' in val_str:
        # Caso 500,50
        val_str = val_str.replace(',', '.')
    # Si solo hay puntos (ej 1.500), asumimos que son miles si son 3 digitos despues, 
    # pero dado el contexto de cedears, mejor tratarlos con cuidado.
    # En tus archivos: "11.400,000" -> punto es mil. "7,680" -> coma es decimal.
    # La logica standard latina funciona bien:
    else:
        # Caso 1400 (sin coma)
        # Si tiene puntos, asumimos que son miles y los quitamos
        val_str = val_str.replace('.', '')
        
    try:
        return float(val_str)
    except ValueError:
        return None

def extract_ticker(simbolo_str, is_usd_file=False):
    """Extrae el ticker base. Ej: 'AAPLD| ...' -> 'AAPL'."""
    if pd.isna(simbolo_str):
        return None
    # Tomar la parte antes del pipe '|'
    ticker = simbolo_str.split('|')[0].strip()
    
    # Si es archivo USD y termina en 'D', quitamos la 'D' para cruzar con el de pesos
    # Ej: AALD -> AAL. (Cuidado con tickers que terminen en D por naturaleza, pero en CEDEARs es la norma)
    if is_usd_file and ticker.endswith('D'):
        return ticker[:-1]
    
    return ticker

def load_and_process(file, is_usd=False):
    # Leemos sin header primero para encontrarlo
    df_raw = pd.read_excel(file, header=None)
    header_idx = find_header_row(df_raw)
    
    # Cargamos de nuevo con el header correcto
    df = pd.read_excel(file, header=header_idx)
    
    # Normalizar nombres de columnas clave
    # A veces hay espacios extra: "Último Precio "
    df.columns = df.columns.str.strip()
    
    if 'Símbolo' not in df.columns or 'Último Precio' not in df.columns:
        st.error(f"No se encontraron las columnas 'Símbolo' o 'Último Precio' en el archivo {'USD' if is_usd else 'ARS'}.")
        return None
        
    # Extraer Ticker Base
    df['Ticker'] = df['Símbolo'].apply(lambda x: extract_ticker(x, is_usd_file=is_usd))
    
    # Limpiar Precio
    df['Precio'] = df['Último Precio'].apply(clean_price)
    
    # Devolver solo lo util
    return df[['Ticker', 'Precio']].dropna()

# --- INTERFAZ PRINCIPAL ---

# 1. Input del Dólar MEP
st.sidebar.header("Parámetros")
dolar_mep_manual = st.sidebar.number_input(
    "Valor Dólar MEP ($)", 
    min_value=0.0, 
    value=1100.0, 
    step=10.0,
    format="%.2f",
    help="Ingresa el valor actual del MEP para comparar arbitrajes."
)

# 2. Carga de Archivos
col1, col2 = st.columns(2)
with col1:
    st.subheader("Archivo en Pesos (ARS)")
    file_ars = st.file_uploader("Subir excel ARS", type=['xlsx', 'xls'], key="ars")

with col2:
    st.subheader("Archivo en Dólares (USD)")
    file_usd = st.file_uploader("Subir excel USD", type=['xlsx', 'xls'], key="usd")

# 3. Procesamiento y Resultados
if file_ars and file_usd:
    with st.spinner('Procesando cotizaciones...'):
        df_ars = load_and_process(file_ars, is_usd=False)
        df_usd = load_and_process(file_usd, is_usd=True)
        
        if df_ars is not None and df_usd is not None:
            # Unir tablas (Inner Join para tener solo los que cotizan en ambas monedas)
            df_merged = pd.merge(
                df_ars, 
                df_usd, 
                on='Ticker', 
                suffixes=('_ARS', '_USD')
            )
            
            # Cálculos
            df_merged['TC_Implicito'] = df_merged['Precio_ARS'] / df_merged['Precio_USD']
            
            # Diferencia % vs MEP Manual
            # Si TC Implicito < MEP: El CEDEAR está "barato" en pesos (o caro en dolares).
            # Gap positivo = Implicito mayor al MEP.
            df_merged['Gap_%'] = ((df_merged['TC_Implicito'] / dolar_mep_manual) - 1) * 100
            
            # Formato para mostrar
            st.markdown("### 🔍 Resultados del Análisis")
            st.metric("Dólar MEP Referencia", f"${dolar_mep_manual:,.2f}")
            
            # Opciones de visualización
            filtro = st.radio("Mostrar oportunidades:", ["Todos", "Más baratos que el MEP (Compra ARS)", "Más caros que el MEP (Venta ARS)"], horizontal=True)
            
            df_show = df_merged.copy()
            if "Más baratos" in filtro:
                df_show = df_show[df_show['TC_Implicito'] < dolar_mep_manual].sort_values('TC_Implicito')
            elif "Más caros" in filtro:
                df_show = df_show[df_show['TC_Implicito'] > dolar_mep_manual].sort_values('TC_Implicito', ascending=False)
            else:
                 df_show = df_show.sort_values('Gap_%')

            # Estilizar tabla
            st.dataframe(
                df_show.style.format({
                    'Precio_ARS': "${:,.2f}",
                    'Precio_USD': "US${:,.2f}",
                    'TC_Implicito': "${:,.2f}",
                    'Gap_%': "{:+.2f}%"
                }).background_gradient(subset=['Gap_%'], cmap='RdYlGn_r'),
                use_container_width=True
            )
            
            st.info("""
            **Interpretación:**
            - **Gap Negativo (Verde)**: El tipo de cambio implícito es menor al MEP. Conviene comprar el CEDEAR en pesos (es como comprar dólares baratos).
            - **Gap Positivo (Rojo)**: El tipo de cambio implícito es mayor al MEP. Conviene vender el CEDEAR en pesos (se obtienen más pesos que vendiendo MEP).
            """)

elif not file_ars or not file_usd:
    st.info("👆 Por favor sube ambos archivos Excel para ver el análisis.")

