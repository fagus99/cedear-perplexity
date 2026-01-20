import streamlit as st
import pandas as pd
import re

st.set_page_config(page_title="Arbitraje CEDEAR", layout="wide")

st.title("💹 Monitor de Arbitraje CEDEAR (Compra ARS -> Venta USD)")
st.markdown("Estrategia: Comprar CEDEAR en Pesos (Punta Vendedora) y vender en Dólares (Punta Compradora).")

# --- FUNCIONES ---
def find_header_row(df):
    for idx, row in df.iterrows():
        if row.astype(str).str.contains("Símbolo", case=False).any(): return idx
    return 0

def clean_price(val):
    if isinstance(val, (int, float)): return float(val)
    if pd.isna(val) or str(val).strip() in ['-', '']: return 0.0
    val_str = str(val)
    val_str = re.sub(r'(ARS|USD|\$)\s*', '', val_str, flags=re.IGNORECASE).strip()
    # Lógica AR: 1.000 (borrar punto) | 2,50 (coma es punto)
    val_str = val_str.replace('.', '').replace(',', '.')
    try: return float(val_str)
    except: return 0.0

def extract_ticker(simbolo_str, is_usd_file=False):
    if pd.isna(simbolo_str): return None
    ticker = simbolo_str.split('|')[0].strip()
    if is_usd_file and ticker.endswith('D'): return ticker[:-1]
    return ticker

def load_data(file, is_usd=False):
    df_raw = pd.read_excel(file, header=None)
    header_idx = find_header_row(df_raw)
    df = pd.read_excel(file, header=header_idx)
    df.columns = df.columns.str.strip()
    
    # Seleccionar columnas correctas
    col_compra = 'Precio Compra'
    col_venta = 'Precio Venta'
    
    if 'Símbolo' not in df.columns or col_venta not in df.columns:
        return None
        
    df['Ticker'] = df['Símbolo'].apply(lambda x: extract_ticker(x, is_usd))
    df['Bid'] = df[col_compra].apply(clean_price)
    df['Ask'] = df[col_venta].apply(clean_price)
    
    # Filtrar liquidez cero
    return df[df['Ask'] > 0][['Ticker', 'Bid', 'Ask']]

# --- APP ---
with st.sidebar:
    st.header("Configuración")
    mep_ref = st.number_input("Dólar MEP Referencia", value=1100.0, step=10.0)

col1, col2 = st.columns(2)
f_ars = col1.file_uploader("Cedear ARS", type=['xlsx'])
f_usd = col2.file_uploader("Cedear USD", type=['xlsx'])

if f_ars and f_usd:
    df_ars = load_data(f_ars, False)
    df_usd = load_data(f_usd, True)
    
    if df_ars is not None and df_usd is not None:
        # Unir
        df = pd.merge(df_ars, df_usd, on='Ticker', suffixes=('_ARS', '_USD'))
        
        # --- CÁLCULO ESPECÍFICO PEDIDO ---
        # Implícito = Ask ARS (lo que pago) / Bid USD (lo que recibo)
        # Evitar división por cero si Bid USD es 0
        df = df[df['Bid_USD'] > 0]
        
        df['TC_Impl'] = df['Ask_ARS'] / df['Bid_USD']
        df['Gap_%'] = ((df['TC_Impl'] / mep_ref) - 1) * 100
        
        # Ordenar: Los más baratos primero (Gap negativo)
        df = df.sort_values('Gap_%')
        
        # Crear columna de "Semáforo" visual usando Pandas Styler de forma segura
        # O simplemente una columna de texto con emojis para evitar errores de matplotlib
        def get_signal(gap):
            if gap < -1.5: return "🟢 Oportunidad" # Más de 1.5% ganancia
            elif gap < 0: return "el verde Leve"
            elif gap > 0: return "🔴 Caro"
            return "Neutro"

        df['Señal'] = df['Gap_%'].apply(get_signal)

        # Mostrar tabla limpia
        st.subheader("Resultados: Compra ARS -> Venta USD")
        
        # Aplicamos estilo de colores SOLO al texto/fondo si es posible, 
        # sino usamos dataframe normal con config.
        
        # Truco para colorear sin matplotlib: usar background_gradient de pandas
        # PERO como fallaba, usaremos una función simple de coloreado celda a celda
        def color_gap(val):
            color = '#d4edda' if val < 0 else '#f8d7da' # Verde claro / Rojo claro
            text_color = '#155724' if val < 0 else '#721c24'
            return f'background-color: {color}; color: {text_color}'

        # Mostrar métricas clave arriba
        best = df.iloc[0]
        st.info(f"🏆 Mejor Oportunidad: **{best['Ticker']}** con TC Implícito de **${best['TC_Impl']:,.2f}** ({best['Gap_%']:.2f}% vs MEP)")

        st.dataframe(
            df[['Ticker', 'Ask_ARS', 'Bid_USD', 'TC_Impl', 'Gap_%', 'Señal']].style.map(color_gap, subset=['Gap_%']).format({
                'Ask_ARS': "${:,.2f}",
                'Bid_USD': "US${:,.2f}",
                'TC_Impl': "${:,.2f}",
                'Gap_%': "{:+.2f}%"
            }),
            use_container_width=True,
            height=600
        )
