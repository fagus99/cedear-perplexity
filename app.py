import streamlit as st
import pandas as pd
import re

# Configuración de la página
st.set_page_config(page_title="Calculadora de Arbitraje CEDEARs", layout="wide")

st.title("💹 Calculadora de Arbitraje y Tipo de Cambio Implícito")
st.markdown("Comparación de puntas Compra/Venta para detectar arbitrajes reales.")

# --- FUNCIONES DE PROCESAMIENTO ---

def find_header_row(df):
    for idx, row in df.iterrows():
        if row.astype(str).str.contains("Símbolo", case=False).any():
            return idx
    return 0

def clean_price(val):
    # 1. Si ya es un número (float o int), lo devolvemos tal cual.
    # Esto evita que '2.115' (float) se convierta en '2115' por error.
    if isinstance(val, (int, float)):
        return float(val)
        
    if pd.isna(val) or str(val).strip() == '-' or str(val).strip() == '':
        return 0.0
    
    val_str = str(val)
    # Eliminar símbolos de moneda
    val_str = re.sub(r'(ARS|USD|\$)\s*', '', val_str, flags=re.IGNORECASE).strip()
    
    # Lógica estricta para formato Argentino/Español:
    # 1. Los puntos '.' son separadores de miles -> Se eliminan.
    # 2. Las comas ',' son separadores decimales -> Se cambian por punto '.' para Python.
    
    # Ejemplo: "2.120,50" -> quitamos punto -> "2120,50" -> cambiamos coma -> "2120.50"
    # Ejemplo caso TQQQ: "2,115" -> quitamos punto (no hay) -> "2,115" -> cambiamos coma -> "2.115"
    
    val_str = val_str.replace('.', '') # Paso 1: Eliminar puntos de miles
    val_str = val_str.replace(',', '.') # Paso 2: Convertir coma decimal a punto
    
    try:
        return float(val_str)
    except ValueError:
        return 0.0


def extract_ticker(simbolo_str, is_usd_file=False):
    if pd.isna(simbolo_str): return None
    ticker = simbolo_str.split('|')[0].strip()
    if is_usd_file and ticker.endswith('D'):
        return ticker[:-1]
    return ticker

def load_and_process(file, is_usd=False):
    df_raw = pd.read_excel(file, header=None)
    header_idx = find_header_row(df_raw)
    df = pd.read_excel(file, header=header_idx)
    df.columns = df.columns.str.strip()
    
    # Validar columnas necesarias
    required_cols = ['Símbolo', 'Precio Compra', 'Precio Venta']
    if not all(col in df.columns for col in required_cols):
        st.error(f"Faltan columnas en el archivo {'USD' if is_usd else 'ARS'}. Se requieren: {required_cols}")
        return None
        
    df['Ticker'] = df['Símbolo'].apply(lambda x: extract_ticker(x, is_usd_file=is_usd))
    
    # Limpiar precios de Compra y Venta
    df['Bid'] = df['Precio Compra'].apply(clean_price) # A lo que el mercado TE COMPRA (Tu precio de venta)
    df['Ask'] = df['Precio Venta'].apply(clean_price)  # A lo que el mercado TE VENDE (Tu precio de compra)
    
    # Filtrar activos sin liquidez (donde precio es 0)
    df = df[(df['Bid'] > 0) & (df['Ask'] > 0)]
    
    return df[['Ticker', 'Bid', 'Ask']]

# --- INTERFAZ PRINCIPAL ---

st.sidebar.header("Parámetros")
dolar_mep_manual = st.sidebar.number_input(
    "Valor Dólar MEP ($)", min_value=0.0, value=1100.0, step=10.0, format="%.2f"
)

col1, col2 = st.columns(2)
with col1:
    file_ars = st.file_uploader("Subir excel ARS (Precio Compra/Venta)", type=['xlsx', 'xls'], key="ars")
with col2:
    file_usd = st.file_uploader("Subir excel USD (Precio Compra/Venta)", type=['xlsx', 'xls'], key="usd")

if file_ars and file_usd:
    with st.spinner('Procesando puntas de mercado...'):
        df_ars = load_and_process(file_ars, is_usd=False)
        df_usd = load_and_process(file_usd, is_usd=True)
        
        if df_ars is not None and df_usd is not None:
            df_merged = pd.merge(df_ars, df_usd, on='Ticker', suffixes=('_ARS', '_USD'))
            
            # --- CÁLCULO DEL TIPO DE CAMBIO IMPLÍCITO ---
            # Para ser conservador en el arbitraje:
            # Si quiero Comprar ARS -> Convertir -> Vender USD:
            # Costo: Ask ARS (lo que pago). Retorno: Bid USD (lo que recibo).
            # TC Implícito "Compra" = Ask ARS / Bid USD
            
            # Si quiero Comprar USD -> Convertir -> Vender ARS (al revés):
            # TC Implícito "Venta" = Bid ARS / Ask USD
            
            # Calculamos un TC Promedio para referencia general
            # (Promedio Puntas ARS) / (Promedio Puntas USD)
            avg_ars = (df_merged['Bid_ARS'] + df_merged['Ask_ARS']) / 2
            avg_usd = (df_merged['Bid_USD'] + df_merged['Ask_USD']) / 2
            df_merged['TC_Impl_Promedio'] = avg_ars / avg_usd
            
            # Gap contra el MEP manual
            df_merged['Gap_%'] = ((df_merged['TC_Impl_Promedio'] / dolar_mep_manual) - 1) * 100
            
            # Ordenar columnas
            cols_show = [
                'Ticker', 
                'Bid_ARS', 'Ask_ARS', 
                'Bid_USD', 'Ask_USD', 
                'TC_Impl_Promedio', 'Gap_%'
            ]
            
            df_show = df_merged[cols_show].sort_values('Gap_%')

            # Métricas
            st.metric("Total Activos Analizados", len(df_show))

            # Tabla Interactiva (Sin matplotlib para evitar errores, usando config nativa)
            st.dataframe(
                df_show,
                column_config={
                    "Bid_ARS": st.column_config.NumberColumn("Cpra ARS", format="$%.2f"),
                    "Ask_ARS": st.column_config.NumberColumn("Vta ARS", format="$%.2f"),
                    "Bid_USD": st.column_config.NumberColumn("Cpra USD", format="US$%.2f"),
                    "Ask_USD": st.column_config.NumberColumn("Vta USD", format="US$%.2f"),
                    "TC_Impl_Promedio": st.column_config.NumberColumn("CCL Implícito", format="$%.2f"),
                    "Gap_%": st.column_config.NumberColumn("Gap vs MEP", format="%.2f%%"),
                },
                use_container_width=True,
                hide_index=True
            )
            
            st.caption("Nota: 'Cpra' y 'Vta' se refieren a las puntas Bid/Ask del mercado. El cálculo usa el promedio de puntas para el TC Implícito.")

