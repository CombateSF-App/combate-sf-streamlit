# Importando bibliotecas
import streamlit as st
import pandas as pd
import geopandas as gpd
import plotly.graph_objects as go
import plotly.express as px
import matplotlib.pyplot as plt
import contextily as ctx
import locale
import io
from io import BytesIO
from PyPDF2 import PdfWriter, PdfReader

# Definindo a língua (utilizado para extrair o mês do formato datetime em português)
# locale.setlocale(locale.LC_TIME, 'Portuguese_Brazil.1252')

# Configurando a nomenclatura da aba no navegador
st.set_page_config(page_title="MAXSATT - Plataforma de Monitoramento", layout="wide")

# Definir o título da página (um texto em fonte grande no topo da página)
# st.markdown("<h1 style='text-align:center;'font-size:40px;'>Plataforma de Monitoramento de Formigas por Sensoriamento Remoto</h1>", unsafe_allow_html=True)

# Adicionando a logo do Maxsatt na aba lateral
st.sidebar.image("logos/logotipo_Maxsatt.png", use_container_width=False, width=150)

# Importando bases de dados (alterar aqui para mudar a base referenciada)
pred_attack = pd.read_parquet("prediction/Filtered_pred_attack.parquet")
stands_all = gpd.read_file("prediction/Talhoes_Manulife_2.shp")

# --- 1. Tratando a base pred_attack ---
pred_attack['COMPANY'] = pred_attack['COMPANY'].str.upper()
pred_attack['FARM'] = pred_attack['FARM'].str.upper()
pred_attack['STAND'] = pred_attack['STAND'].str.upper()
pred_attack['DATE'] = pd.to_datetime(pred_attack['DATE']).dt.date

# --- 2. Tratando a base stands_all ---
# Reproject to EPSG:4326 first to ensure all geometries have a valid CRS
stands_all = stands_all.to_crs(epsg=4326)

# Uppercase and formatting
stands_all['COMPANY'] = stands_all['Companhia'].str.upper()
stands_all['FARM'] = stands_all['Fazenda'].str.replace(" ", "_")
stands_all['STAND'] = stands_all.apply(lambda row: f"{row['Fazenda']}_{row['CD_TALHAO']}", axis=1)

# --- 3. Corrigindo geometria ---
# Verifica se há problemas de geometria inválida e corrige
stands_all['geometry'] = stands_all['geometry'].apply(lambda geom: geom.buffer(0) if not geom.is_valid else geom)

# --- 4. Calculando área de cada talhão ---
# Projeta para EPSG:32722 para cálculo de área em metros quadrados
stands_all = stands_all.to_crs("EPSG:32722")

# Calcula a área em hectares para cada registro de talhão
stands_all['area_ha'] = stands_all['geometry'].area / 10000  # m² to ha

# --- 5. Calculando área total por fazenda ---
def calculate_farm_area(group):
    """Calcula a área total por fazenda em hectares"""
    return group['geometry'].area.sum() / 10000  # Convert m² to ha

# Aplica a função de cálculo de área por fazenda
farm_area_df = stands_all.groupby('FARM')['geometry'].apply(calculate_farm_area).reset_index(name='farm_total_area_ha')

# --- 6. Atualiza a base com as áreas totais ---
stands_all = stands_all.merge(farm_area_df, on='FARM', how='left')

# Debugging output to verify areas
print("Sample areas (ha):", stands_all[['FARM', 'farm_total_area_ha']].drop_duplicates().head())