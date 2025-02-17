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
locale.setlocale(locale.LC_TIME, 'Portuguese_Brazil.1252')

# Configurando a nomenclatura da aba no navegador
st.set_page_config(page_title="MAXSATT - Plataforma de Monitoramento", layout="wide")

# Definir o título da página (um texto em fonte grande no topo da página)
#st.markdown("<h1 style='text-align:center;'font-size:40px;'>Plataforma de Monitoramento de Formigas por Sensoriamento Remoto</h1>", unsafe_allow_html=True)

# Adicionando a logo do Maxsatt na aba lateral
st.sidebar.image("logos\logotipo_Maxsatt.png", width=150)

# Importando bases de dados (alterar aqui para mudar a base referenciada)
pred_attack = pd.read_parquet("prediction\Filtered_pred_attack.parquet")
stands_all = gpd.read_file("prediction\Talhoes_Manulife_2.shp")

# Tratando a base pred_attack
pred_attack['COMPANY'] = pred_attack['COMPANY'].str.upper()
pred_attack['FARM'] = pred_attack['FARM'].str.upper()
pred_attack['STAND'] = pred_attack['STAND'].str.upper()
pred_attack['DATE'] = pd.to_datetime(pred_attack['DATE']).dt.date

# Tratando a base stands_all
stands_all = stands_all.to_crs(epsg=4326)
stands_all['COMPANY'] = stands_all['Companhia'].str.upper()
stands_all['FARM'] = stands_all['Fazenda'].str.replace(" ", "_")
stands_all['STAND'] = stands_all.apply(lambda row: f"{row['Fazenda']}_{row['CD_TALHAO']}", axis=1)
stands_all['area_ha'] = stands_all['geometry'].area / 10000

# Função para encontrar a área de cada fazenda
def calculate_farm_area(group):
    farm_area_m2 = group['geometry'].to_crs("EPSG:32722").area.sum()
    farm_area_ha = farm_area_m2 / 10000
    return farm_area_ha

# Adicionando uma coluna para área de cada fazenda
stands_all['farm_total_area_ha'] = stands_all.groupby('FARM').apply(calculate_farm_area).reindex(stands_all['FARM']).values

# Configurando os filtros
# Get the single company name (assuming there's only one unique company)
empresa = pred_attack['COMPANY'].unique()[0]

# Display the title in the sidebar
st.sidebar.write(f"**Empresa:** {empresa}")

fazenda = st.sidebar.selectbox('Selecione a Fazenda', options=pred_attack[pred_attack['COMPANY'] == empresa]['FARM'].unique())
talhao = st.sidebar.selectbox('Selecione o Talhão', options=pred_attack[(pred_attack['FARM'] == fazenda)]['STAND'].unique())
sorted_dates = sorted(pred_attack['DATE'].unique(), reverse=True)

data = sorted_dates[0]

st.sidebar.write(f"**Data:** {data}")

# Bases filtradas com diferentes granularidades (pred_attack)
filtered_data_company_date = pred_attack[(pred_attack['COMPANY'] == empresa) & (pred_attack['DATE'] == data)]
filtered_data_farm = pred_attack[(pred_attack['COMPANY'] == empresa) & (pred_attack['FARM'] == fazenda) & (pred_attack['DATE'] == data)]
filtered_data = pred_attack[(pred_attack['COMPANY'] == empresa) & (pred_attack['FARM'] == fazenda) & (pred_attack['STAND'] == talhao) & (pred_attack['DATE'] == data)]
filtered_farm = pred_attack[pred_attack['FARM'] == fazenda]
filtered_company = pred_attack[pred_attack['COMPANY'] == empresa]

# Definindo a variável QT
QT = pred_attack['canopycov'].quantile(0.10)

# Bases filtradas com diferentes granularidades (stands_all)
stands_all_filtered = stands_all[stands_all['COMPANY'] == empresa]
stands_all_filtered = stands_all_filtered.to_crs("EPSG:32722")
stands_sel = stands_all[stands_all['STAND'] == talhao]
stands_sel_farm = stands_all[stands_all['FARM'] == fazenda]

# Junção da pred_attack com stands_all (filtrada por data) e tratamento da planilha resultante
merged_df = filtered_data_company_date.merge(stands_all_filtered[['FARM', 'STAND', 'geometry', 'farm_total_area_ha']], on=['FARM', 'STAND'], how='left')
merged_df = gpd.GeoDataFrame(merged_df, geometry='geometry', crs="EPSG:32722")
merged_df['Status'] = ['Desfolha' if x < QT else 'Saudavel' for x in merged_df['canopycov']]
merged_df['area_ha'] = merged_df['geometry'].area / 10000

# Base auxiliar com uma linha para cada fazenda
unique_area_per_farm = merged_df.drop_duplicates(subset=['FARM'])

# Juntando pred_attack com stands_all (sem filtros) e tratando a planilha resultante
merged_df_all = filtered_company.merge(stands_all_filtered[['FARM', 'STAND', 'geometry']], on=['FARM', 'STAND'], how='left')
merged_df_all = gpd.GeoDataFrame(merged_df_all, geometry='geometry', crs="EPSG:32722")
merged_df_all['Status'] = ['Desfolha' if x < QT else 'Saudavel' for x in merged_df_all['canopycov']]
merged_df_all['area_ha'] = merged_df_all['geometry'].area / 10000

# Criando a base agrupada por fazenda e status e tratando-a
grouped_farm = (merged_df_all.dropna(subset=['Status'])
                .groupby(['DATE', 'Status', 'FARM'])
                .agg(count=('Status', 'size'))
                .reset_index()
                .merge(unique_area_per_farm[['FARM', 'farm_total_area_ha']], on='FARM', how='left'))
grouped_farm['farm_desfolha_area_ha'] = grouped_farm['count']/100
grouped_farm['total'] = grouped_farm.groupby(['DATE', 'FARM'])['count'].transform('sum')
grouped_farm['percentage'] = (grouped_farm['count'] / grouped_farm['total']) * 100
grouped_farm = grouped_farm[grouped_farm['Status'] == 'Desfolha'].sort_values(by='DATE')
grouped_farm['farm_total_area_ha'] = grouped_farm['farm_total_area_ha'].round(1)
grouped_farm['percentage'] = grouped_farm['percentage'].round(1)

# Base filtrada para data selecionada
grouped_farm_date = grouped_farm[grouped_farm['DATE']==data]

# Base auxiliar com uma linha para cada talhão
unique_area_per_stand = merged_df.drop_duplicates(subset=['FARM', 'STAND'])
unique_area_per_stand.rename(columns={'area_ha': 'stand_total_area_ha'}, inplace=True)

# Criando a base agrupada por talhão e status e tratando-a
grouped_stand = (merged_df_all.dropna(subset=['Status'])
                .groupby(['DATE', 'Status', 'FARM', 'STAND'])
                .agg(count=('Status', 'size'))
                .reset_index()
                .merge(unique_area_per_stand[['STAND', 'stand_total_area_ha']], on='STAND', how='left'))
                
grouped_stand['stand_desfolha_area_ha'] = grouped_stand['count']/100
grouped_stand['total'] = grouped_stand.groupby(['DATE', 'FARM', 'STAND'])['count'].transform('sum')
grouped_stand['percentage'] = (grouped_stand['stand_desfolha_area_ha'] / grouped_stand['stand_total_area_ha']) * 100
grouped_stand = grouped_stand[grouped_stand['Status'] == 'Desfolha'].sort_values(by='DATE')
grouped_stand['stand_total_area_ha'] = grouped_stand['stand_total_area_ha'].round(1)
grouped_stand['percentage'] = grouped_stand['percentage'].round(1)
grouped_stand = grouped_stand.drop_duplicates(subset=['DATE', 'FARM', 'STAND'])
grouped_stand = grouped_stand.sort_values(by='stand_desfolha_area_ha', ascending=False)

# Base filtrada para data selecionada
grouped_stand_date = grouped_stand[grouped_stand['DATE']==data]

# Base filtrada para a fazenda selecionada
grouped_stand_farm = grouped_stand[grouped_stand['FARM']==fazenda]
grouped_stand_farm = grouped_stand_farm.sort_values(by='stand_desfolha_area_ha', ascending=False)

# PREPARAR AS PLANILHAS PARA DOWNLOAD

# Planilha fazendas
# Criar coluna de mês e filtrar por data
grouped_farm['DATE'] = pd.to_datetime(grouped_farm['DATE'])
grouped_farm['Mes'] = grouped_farm['DATE'].dt.strftime('%b').str.lower()

# Criar coluna de porcentagem média de desfolha por mês, usando uma base auxiliar
average_farm = (
    grouped_farm
    .groupby(['FARM', 'Mes'])['percentage']
    .mean()
    .reset_index()
    .rename(columns={'percentage': 'Average%'}))
average_farm['Average%'] = average_farm['Average%'].round(1)
grouped_farm = grouped_farm.merge(average_farm, on=['FARM', 'Mes'], how='left')

# Criando as colunas de recomendação
grouped_farm['SDD'] = grouped_farm.apply(lambda row: row['farm_total_area_ha'] if row['Average%'] < 0.5 else None, axis=1)
grouped_farm['Controle 9M'] = grouped_farm.apply(lambda row: row['farm_total_area_ha'] if 0.5 <= row['Average%'] <= 5 else None, axis=1)
grouped_farm['Controle 3M'] = grouped_farm.apply(lambda row: row['farm_total_area_ha'] if row['Average%'] > 5 else None, axis=1)
grouped_farm = grouped_farm.sort_values(by=['FARM', 'DATE'])
grouped_farm['percentage_diff'] = grouped_farm.groupby('FARM')['percentage'].diff()
grouped_farm['percentage_diff'] = grouped_farm['percentage_diff'].round(1)
grouped_farm['Outra desfolha'] = grouped_farm.apply(lambda row: row['farm_total_area_ha'] if row['percentage_diff'] > 8 else None, axis=1)
grouped_farm.loc[grouped_farm['Outra desfolha'].notna(), 'Controle 3M'] = None

grouped_farm_temp = grouped_farm.copy()

grouped_farm_excel = grouped_farm.copy()
grouped_farm_excel = (grouped_farm_excel.rename(columns={
    'DATE': 'Data', 'FARM': 'Fazenda', 'farm_total_area_ha': 'Area total da fazenda', 
    'farm_desfolha_area_ha': 'Area total em desfolha', 'percentage': 'Porcentagem'}))

grouped_farm_excel.drop(columns = ['count', 'total', 'Mes', 'percentage_diff'], inplace=True)

# Definindo a planilha a ser exportada
#excel_farm = grouped_farm_excel.to_excel(index=False).encode('utf-8')

# Planilha talhões
# Criar coluna de mês
grouped_stand['DATE'] = pd.to_datetime(grouped_stand['DATE'])
grouped_stand['Mes'] = grouped_stand['DATE'].dt.strftime('%b').str.lower()

# Criar coluna de porcentagem média de desfolha por mês, usando uma base auxiliar
average_stand = (
    grouped_stand
    .groupby(['STAND', 'Mes'])['percentage']
    .mean()
    .reset_index()
    .rename(columns={'percentage': 'Average%'}))
average_stand['Average%'] = average_stand['Average%'].round(1)
grouped_stand = grouped_stand.merge(average_stand, on=['STAND', 'Mes'], how='left')

# Criando as colunas de recomendação
grouped_stand['SDD'] = grouped_stand.apply(lambda row: row['stand_total_area_ha'] if row['Average%'] < 0.5 else None, axis=1)
grouped_stand['Controle 9M'] = grouped_stand.apply(lambda row: row['stand_total_area_ha'] if 0.5 <= row['Average%'] <= 5 else None, axis=1)
grouped_stand['Controle 3M'] = grouped_stand.apply(lambda row: row['stand_total_area_ha'] if row['Average%'] > 5 else None, axis=1)
grouped_stand = grouped_stand.sort_values(by=['STAND', 'DATE'])
grouped_stand['percentage_diff'] = grouped_stand.groupby('STAND')['percentage'].diff()
grouped_stand['percentage_diff'] = grouped_stand['percentage_diff'].round(1)
grouped_stand['Outra desfolha'] = grouped_stand.apply(lambda row: row['stand_total_area_ha'] if row['percentage_diff'] > 8 else None, axis=1)
grouped_stand.loc[grouped_stand['Outra desfolha'].notna(), 'Controle 3M'] = None

grouped_stand_temp = grouped_stand.copy()

grouped_stand_excel = grouped_stand.copy()
grouped_stand_excel = (grouped_stand_excel.rename(columns={
    'DATE': 'Data', 'FARM': 'Fazenda', 'STAND': 'Talhao', 'stand_total_area_ha': 'Area total do talhao', 
    'stand_desfolha_area_ha': 'Area total em desfolha', 'percentage': 'Porcentagem'}))

grouped_stand_excel.drop(columns = ['count', 'total', 'Mes', 'percentage_diff'], inplace=True)

# Definindo a planilha a ser exportada
#excel_stand = grouped_stand_excel.to_excel(index=False).encode('utf-8')

# TABELA RECOMENDAÇÃO GERAL

grouped_stand_data = grouped_stand[grouped_stand['DATE'].dt.date==data]

recommendations = {
    'SDD': 'Area ha – Sem Desfolha Detectada: Seguir Monitorando',
    'Controle 9M': 'Area ha - Infestação com baixo Índice de Desfolha: Programar Controle nos Próximos 9 Meses',
    'Controle 3M': 'Area ha - Infestação com Médio a Alto Índice de Desfolha: Programar Controle Imediato ou em Até 3 Meses',
    'Outra desfolha': 'Area ha - Monitorar o aumento da desfolha, investigando 	causas como pragas, doenças ou estresse, para evitar danos à produção.'
}

recomendacao_geral = pd.DataFrame({
    'Recomendação': ['SDD', 'Controle 9M', 'Controle 3M', 'Outra desfolha'],
    'Área': [
        grouped_stand_data['SDD'].sum(),
        grouped_stand_data['Controle 9M'].sum(),
        grouped_stand_data['Controle 3M'].sum(),
        grouped_stand_data['Outra desfolha'].sum()
    ],
    'O que?': [recommendations['SDD'], recommendations['Controle 9M'], recommendations['Controle 3M'], recommendations['Outra desfolha']]
})

# TABELA RECOMENDAÇÃO FAZENDA

grouped_stand_tabela = grouped_stand_data[grouped_stand_data['FARM']==fazenda]

recomendacao_farm = pd.DataFrame({
    'Recomendação': ['SDD', 'Controle 9M', 'Controle 3M', 'Outra desfolha'],
    'Área': [
        grouped_stand_tabela['SDD'].sum(),
        grouped_stand_tabela['Controle 9M'].sum(),
        grouped_stand_tabela['Controle 3M'].sum(),
        grouped_stand_tabela['Outra desfolha'].sum()
    ],
    'O que?': [recommendations['SDD'], recommendations['Controle 9M'], recommendations['Controle 3M'], recommendations['Outra desfolha']]
})

# TABELA RESUMO MONITORAMENTO

grouped_farm_date_tabela = grouped_farm_date[['FARM', 'farm_total_area_ha']].reset_index(drop=True)
grouped_farm_date_tabela = grouped_farm_date_tabela.rename(columns={
    'FARM': 'Fazenda',
    'farm_total_area_ha': 'Área monitorada (ha)'
})

# TABELA RESUMO MONITORAMENTO FAZENDA

grouped_stand_date_tabela = grouped_stand_date[['STAND', 'stand_total_area_ha']].reset_index(drop=True)
grouped_stand_date_tabela = grouped_stand_date_tabela.rename(columns={
    'STAND': 'Talhão',
    'stand_total_area_ha': 'Área monitorada (ha)'
})

# BORDA ARREDONDADA

def bg_border(color):
    st.markdown(
        f"""
        <style>
        .stPlotlyChart {{
        outline: 3px solid {color};
        border-radius: 5px;
        box-shadow: 0 4px 8px 0 rgba(0, 0, 0, 0.20), 0 6px 20px 0 rgba(0, 0, 0, 0.30);
        }}
        </style>
        """, unsafe_allow_html=True
    )

# CARDS ESTILO

def create_card(title, value):
    return f"""
    <div style="
        background-color: #f5f5f5;
        border-radius: 10px;
        padding: 20px;
        margin: 10px;
        box-shadow: 2px 2px 5px rgba(0, 0, 0, 0.1);
        text-align: center;
        font-family: Arial, sans-serif;
    ">
        <h4 style="margin: 0; color: #333; font-size: 20px;">{title}</h4>
        <h1 style="margin: 0; color: #000000;font-size: 35px;">{value}</h1>
    </div>
    """

# CARD ÁREA TOTAL MONITORADA

total_area_df = stands_all[stands_all['COMPANY'] == empresa]
total_area_m2 = total_area_df['geometry'].to_crs("EPSG:32722").area.sum()
total_area_ha = total_area_m2 / 10000
total_area_ha_rounded = round(total_area_ha, 1)

# CARD ÁREA TOTAL DESFOLHA

total_area_desfolha = grouped_farm_date['farm_desfolha_area_ha'].sum()
total_area_desfolha_rounded = round(total_area_desfolha, 1)

# CARD NÚMERO DE FAZENDAS NA EMPRESA

filtered_farms = stands_all[stands_all['COMPANY'] == empresa]
num_unique_farms = filtered_farms['FARM'].nunique()

# CARD NÚMERO DE TALHOES NA EMPRESA

num_unique_stands = filtered_farms['STAND'].nunique()

# CARD ÁREA FAZENDA 

farm_area_df = stands_all[stands_all['FARM'] == fazenda]
farm_area_m2 = farm_area_df['geometry'].to_crs("EPSG:32722").area.sum()
farm_area_ha = farm_area_m2 / 10000
farm_area_ha_rounded = round(farm_area_ha, 1)

# CARD ÁREA DESFOLHA FAZENDA

farm_area_desfolha = grouped_farm_date[grouped_farm_date['FARM']==fazenda]['farm_desfolha_area_ha'].sum()
farm_area_desfolha_rounded = round(farm_area_desfolha, 1)

# CARD NÚMERO DE TALHÕES NA FAZENDA

filtered_stands = stands_all[stands_all['FARM'] == fazenda]
num_unique_stands_farm = filtered_stands['STAND'].nunique()

# CARD ÁREA TOTAL TALHÃO

stand_area_df = stands_all[stands_all['STAND'] == talhao]
stand_area_m2 = stand_area_df['geometry'].to_crs("EPSG:32722").area.sum()
stand_area_ha = stand_area_m2 / 10000
stand_area_ha_rounded = round(stand_area_ha, 1)

# CARD ÁREA DESFOLHA TALHÃO

stand_area_desfolha = grouped_stand_date[grouped_stand_date['STAND']==talhao]['stand_desfolha_area_ha'].sum()
stand_area_desfolha_rounded = round(stand_area_desfolha, 1)

# GRÁFICO DE ROSCA ÁREA MONITORADA  

# Definindo variáveis auxiliares
farm_percentage = (farm_area_m2 / total_area_m2) * 100
healthy_percentage = 100 - farm_percentage
other_area_ha = total_area_ha - farm_area_ha

# Definindo parâmetros para o gráfico
sizes = [other_area_ha, farm_area_ha]
colors = ['lightgray', 'darkgreen']
labels = ['Demais fazendas', fazenda]

# Calculate total desfolha and healthy areas
total_area_desfolha = grouped_farm_date['farm_desfolha_area_ha'].sum()
total_area_healthy = total_area_ha - total_area_desfolha

# Define labels and sizes for the pie chart
labels = ['Área Sem Desfolha Detectada', 'Área em Desfolha']
sizes = [total_area_healthy, total_area_desfolha]
colors = ['darkgreen', 'orange']  # Adjust colors to your preference

# Generate the pie chart with custom labels and colors
fig1 = go.Figure()

fig1.add_trace(go.Pie(
    labels=['Área Total Sem Desfolha Detectada', 'Área Total c/ Desfolha'],
    values=[total_area_healthy, total_area_desfolha],
    marker=dict(colors=['darkgreen', 'orange']),
    textinfo='percent',
    textfont=dict(size=20),  # Increase percentage text size inside the pie chart
    hovertemplate=(
        '<b>%{label}</b><br>'
        'Área: %{value:.2f} ha<br>'
        'Porcentagem: %{percent:.1%}<extra></extra>'
    ),
    showlegend=True
))

# Update the layout to move the legend to the bottom of the page
fig1.update_layout(
    title={
        'text': "Área Monitorada",
        'y': 0.95,
        'x': 0.5,
        'xanchor': 'center',
        'yanchor': 'top',
        'font': {'color': 'black', 'size': 21}
    },
    paper_bgcolor='#f5f5f5',
    plot_bgcolor='rgba(0,0,0,0)',
    showlegend=True,
    legend=dict(
        orientation="h",  # Horizontal legend
        yanchor="top",
        y=-0.3,  # Move legend farther below the pie chart (adjust if needed)
        xanchor="center",
        x=0.5,
        font=dict(size=14, color='black'),
        bgcolor='rgba(0,0,0,0)'  # Transparent background for the legend
    )
)

grouped_farm_date['percentage'] = (
    grouped_farm_date['farm_desfolha_area_ha'] / grouped_farm_date['farm_total_area_ha']
) * 100

# Sort by desfolha area percentage and get top 10 farms
top_10_farms = grouped_farm_date.sort_values(by='percentage', ascending=False).head(10)

# Calculate the healthy percentage for each farm
top_10_farms['healthy_percentage'] = 100 - top_10_farms['percentage']

# Generate the stacked bar chart
fig2 = go.Figure()

# Add the red portion for desfolha percentage
fig2.add_trace(go.Bar(
    x=top_10_farms['percentage'],
    y=top_10_farms['FARM'],
    orientation='h',
    name='Área em Desfolha',
    marker=dict(color='orange'),
    text=top_10_farms['percentage'].round(1).astype(str) + '%',
    textposition='inside'
))

# Add the green portion for the healthy area percentage
fig2.add_trace(go.Bar(
    x=top_10_farms['healthy_percentage'],
    y=top_10_farms['FARM'],
    orientation='h',
    name='Área Sem Desfolha Detectada',
    marker=dict(color='darkgreen'),
    text=top_10_farms['healthy_percentage'].round(1).astype(str) + '%',
    textposition='inside'
))

fig2.update_layout(
    title='Top 10 Fazendas com Maior Percentual de Desfolha',
    xaxis_title=dict(text="Percentual de Área (%)", font=dict(size=14, color='black')),
    yaxis_title=dict(text="Fazenda", font=dict(size=14, color='black')),
    xaxis=dict(
        tickfont=dict(size=12, color='black'),
        range=[0, 100],  # Ensure the full 0-100% scale is displayed
    ),
    yaxis=dict(
        tickfont=dict(size=12, color='black'),
        autorange='reversed'
    ),
    barmode='stack',  # Stack the bars
    title_font=dict(size=16, family='Arial', color='black'),
    paper_bgcolor='#f5f5f5',
    plot_bgcolor='rgba(0,0,0,0)',
    showlegend=True,
    legend=dict(
        orientation='h',  # Horizontal orientation for the legend
        yanchor='top',
        y=-0.3,           # Position below the graph (adjust if needed)
        xanchor='center',
        x=0.5,
        font=dict(size=12, color='black'),
        bgcolor='rgba(0,0,0,0)'  # Transparent background for the legend
    )
)

# TALHÕES MAIS INFESTADOS GERAL

# Calculate percentage of desfolha for each stand
grouped_stand_date['desfolha_percentage'] = (grouped_stand_date['stand_desfolha_area_ha'] / grouped_stand_date['stand_total_area_ha']) * 100

# Sort by percentage and get the top 10
top_10_stands_geral = grouped_stand_date.sort_values(by='percentage', ascending=False).head(10)

# Define gradient colors for the bars
colors = ["#ffae00", "#ffbd00", "#ffcb00", "#ffda00", "#ffe800", 
          "#fff700", "#c8eb0a", "#92df14", "#5bd21d", "#24c627"]

# Generate the bar chart
fig3 = go.Figure()
fig3.add_trace(go.Bar(
    x=top_10_stands_geral['percentage'],
    y=top_10_stands_geral['STAND'],
    orientation='h',
    marker=dict(color=colors),
    text=top_10_stands_geral['percentage'].round(1).astype(str) + '%',  # Display percentage text
    textposition='auto'
))

# Adjust chart layout
fig3.update_layout(
    title='Top 10 Talhões com Maior Percentual de Desfolha',
    xaxis_title=dict(text="Percentual de Desfolha (%)", font=dict(size=14, color='black')),
    yaxis_title=dict(text="Talhão", font=dict(size=14, color='black')),
    title_font=dict(size=16, family='Arial', color='black'),
    xaxis=dict(
        title="Percentual de Desfolha (%)",
        tickfont=dict(size=12, color='black'),
        range=[0, 100]  # Set fixed range for the percentage scale
    ),
    yaxis=dict(tickfont=dict(size=12, color='black'), autorange='reversed'),
    paper_bgcolor='#f5f5f5',
    plot_bgcolor='rgba(0,0,0,0)'
)

# Variável auxiliar
healthy_area_farm = farm_area_ha_rounded - farm_area_desfolha_rounded

# Definindo parâmetros para o gráfico
sizes = [farm_area_desfolha_rounded, healthy_area_farm]
colors = ['orange', 'darkgreen']
labels = ['Área Total c/ Desfolha', 'Área Total Sem Desfolha Detectada']

# Gerando o gráfico (Pie Chart)
fig4 = go.Figure()
fig4.add_trace(go.Pie(
    labels=labels,
    values=sizes,
    marker=dict(colors=colors),
    textinfo='percent',
    texttemplate='%{percent:.1%}',  # Percentages displayed inside
    insidetextorientation='horizontal',  # Horizontal text orientation
    hovertemplate=(
        '<b>%{label}</b><br>'
        'Área: %{value:.2f} ha<br>'
        'Porcentagem: %{percent:.1%}<extra></extra>'
    ),
    textfont=dict(size=20, color='white')  # Larger white text for percentages
))

# Ajustando o visual do gráfico
fig4.update_layout(
    title={'text': "Área Monitorada na fazenda selecionada", 'y': 0.95, 'x': 0.5, 'xanchor': 'center', 'yanchor': 'top', 'font': {'color': 'black', 'size': 21, 'family': 'Arial Black'}},
    paper_bgcolor='#f5f5f5',
    plot_bgcolor='rgba(0,0,0,0)',
    showlegend=True,
    legend=dict(
        orientation='h',          # Horizontal legend at the bottom
        yanchor='bottom',
        y=-0.2,                   # Position below the chart
        xanchor='center',
        x=0.5,
        font=dict(size=14, color='black'),
        bgcolor='rgba(0, 0, 0, 0)'
    )
)

# make grouped_stand_farm_date a date
grouped_stand_farm['DATE'] = pd.to_datetime(grouped_stand_farm['DATE'])

grouped_stand_farm_date = grouped_stand_farm[grouped_stand_farm['DATE'].dt.date==data]


# Base auxiliar: Calculate percentage of desfolha for each stand
grouped_stand_farm_date['desfolha_percentage'] = (grouped_stand_farm_date['stand_desfolha_area_ha'] / grouped_stand_farm_date['stand_total_area_ha']) * 100

# Sort by percentage in descending order and get the top 10 stands
top_10_stands_farm = grouped_stand_farm_date.sort_values(by='percentage', ascending=False).head(10)

# Define colors for the gradient (optional)
colors = ["#ffae00", "#ffbd00", "#ffcb00", "#ffda00", "#ffe800", 
          "#fff700", "#c8eb0a", "#92df14", "#5bd21d", "#24c627"]

# Generate the bar chart
fig5 = go.Figure()
fig5.add_trace(go.Bar(
    x=top_10_stands_farm['percentage'],
    y=top_10_stands_farm['STAND'],
    orientation='h',
    marker=dict(color=colors),
    text=top_10_stands_farm['percentage'].round(1).astype(str) + '%',  # Display percentage as text
    textposition='auto'
))

# Adjust chart appearance
fig5.update_layout(
    title='Top 10 Talhões com Maior Percentual de Desfolha na fazenda {}'.format(fazenda),
    xaxis_title=dict(text="Percentual de Desfolha (%)", font=dict(size=14, color='black')),
    yaxis_title=dict(text="Talhão", font=dict(size=14, color='black')),
    title_font=dict(size=16, family='Arial', color='black'),
    xaxis=dict(
        title="Percentual de Desfolha (%)",
        tickfont=dict(size=12, color='black'),
        range=[0, 100]  # Set fixed range for the percentage scale
    ),
    yaxis=dict(tickfont=dict(size=12, color='black'), autorange='reversed'),
    paper_bgcolor='#f5f5f5',
    plot_bgcolor='rgba(0,0,0,0)'
)

# Variável auxiliar
healthy_area_stand = stand_area_ha_rounded - stand_area_desfolha_rounded

# Definindo parâmetros para o gráfico
sizes = [stand_area_desfolha_rounded, healthy_area_stand]
colors = ['orange', 'darkgreen']
labels = ['Área Total c/ Desfolha', 'Área Total Sem Desfolha Detectada']

fig6 = go.Figure()
fig6.add_trace(go.Pie(
    labels=labels,
    values=sizes,
    marker=dict(colors=colors),
    textinfo='percent',
    texttemplate='%{percent:.1%}',  # Percentages displayed inside
    textposition='inside',          # Forces text to stay inside
    insidetextorientation='auto',   # Dynamically adjusts text orientation
    hovertemplate=(
        '<b>%{label}</b><br>'
        'Área: %{value:.2f} ha<br>'
        'Porcentagem: %{percent:.1%}<extra></extra>'
    ),
    textfont=dict(size=18, color='white')  # Reduced size to fit inside small segments
))

# Ajustando o visual do gráfico
fig6.update_layout(
    title={'text': f"Área Monitorada - {talhao}", 'y': 0.95, 'x': 0.5, 'xanchor': 'center', 'yanchor': 'top', 'font': {'color': 'black', 'size': 21, 'family': 'Arial Black'}},
    paper_bgcolor='#f5f5f5',
    plot_bgcolor='rgba(0,0,0,0)',
    showlegend=True,
    legend=dict(
        orientation='h',          # Horizontal legend at the bottom
        yanchor='bottom',
        y=-0.2,                   # Position below the chart
        xanchor='center',
        x=0.5,
        font=dict(size=14, color='black'),
        bgcolor='rgba(0, 0, 0, 0)'
    )
)
# MAPA DE CALOR FAZENDA

# Criando o mapa
fig7, ax = plt.subplots(figsize=(6, 3), constrained_layout=True)
stands_sel.plot(ax=ax, edgecolor='black', facecolor='none', linewidth=0.5)
sc = ax.scatter(
    filtered_data_farm['X'], filtered_data_farm['Y'], 
    c=filtered_data_farm['canopycov'], cmap='RdYlGn', 
    s=1, alpha=1, marker='s', label='Cobertura do Dossel (%)')

# Destacando o talhão selecionado
region_to_highlight = stands_all[stands_all['STAND'] == talhao]
region_to_highlight.plot(ax=ax, edgecolor='red', linewidth=0.8, facecolor='none', label='Região Destaque')

# Renderizando o mapa ao fundo
ctx.add_basemap(ax, crs=stands_sel.crs, source=ctx.providers.Esri.WorldImagery, attribution=False)

# Ajustando o visual
ax.axis('off')
cbar = plt.colorbar(sc, ax=ax, fraction=0.02, pad=0.02)
cbar.set_label("Cobertura do dossel (%)", fontsize=8)
cbar.ax.tick_params(labelsize=6)

# MAPA DE CALOR TALHÃO

# Criando o mapa
fig8, ax = plt.subplots(figsize=(6, 3), constrained_layout=True)
stands_sel.plot(ax=ax, edgecolor='black', facecolor='none', linewidth=0.5)
sc = ax.scatter(filtered_data['X'], filtered_data['Y'], 
                c=filtered_data['canopycov'], cmap='RdYlGn', 
                s=1, alpha=1, marker='s', label='Cobertura do Dossel (%)')

# Renderizando o mapa ao fundo
ctx.add_basemap(ax, crs=stands_sel.crs, source=ctx.providers.Esri.WorldImagery, attribution=False)

# Ajustando o visual
ax.axis('off')
cbar = plt.colorbar(sc, ax=ax, fraction=0.02, pad=0.02)
cbar.set_label("Cobertura do dossel (%)", fontsize=8)
cbar.ax.tick_params(labelsize=6)

# GRÁFICO TEMPORAL POR FAZENDA

# Base auxiliar
monthly_avg_farm = grouped_farm_temp[grouped_farm_temp['FARM']==fazenda]

# Base auxiliar filtrada até a data selecionada
monthly_avg_farm_filtered = monthly_avg_farm[monthly_avg_farm['DATE'] <= pd.to_datetime(data)]

# Gerando o gráfico
fig9 = go.Figure()
fig9.add_trace(go.Scatter(
    x=monthly_avg_farm_filtered['Mes'],
    y=monthly_avg_farm_filtered['Average%'],
    mode='lines+markers+text',
    name='Média Mensal (%)',
    line=dict(color='red', width=2),
    marker=dict(size=6),
    text=monthly_avg_farm_filtered['Average%'].round(1),
    textposition='top center',
    textfont=dict(size=12, color='black')
))

# Ajustando o visual
fig9.update_layout(
    title="Média desfolha (%) por mês na fazenda",
    xaxis_title=dict(text="Mês", font=dict(size=14, color='black')),
    yaxis_title=dict(text="Desfolha (%)", font=dict(size=14, color='black')),
    title_font=dict(size=16, family='Arial', color='black'),
    xaxis=dict(tickfont=dict(size=12, color='black')),
    yaxis=dict(tickfont=dict(size=12, color='black')),
    showlegend=False,
    paper_bgcolor='#f5f5f5',
    plot_bgcolor='rgba(0,0,0,0)'
)

# GRÁFICO TEMPORAL POR TALHÃO

# Base auxiliar
monthly_avg_stand = grouped_stand_temp[grouped_stand_temp['STAND']==talhao]
# Base auxiliar filtrada até a data selecionada
monthly_avg_stand_filtered = monthly_avg_stand[monthly_avg_stand['DATE'] <= pd.to_datetime(data)]

# Gerando o gráfico
fig10 = go.Figure()
fig10.add_trace(go.Scatter(
    x=monthly_avg_stand_filtered['Mes'],
    y=monthly_avg_stand_filtered['Average%'],
    mode='lines+markers+text',
    name='Média Mensal (%)',
    line=dict(color='red', width=2),
    marker=dict(size=6),
    text=monthly_avg_stand_filtered['Average%'].round(2),
    textposition='top center',
    textfont=dict(size=12, color='black')
))

# Ajustando o visual
fig10.update_layout(
    title="Média desfolha (%) por mês no talhão",
    xaxis_title=dict(text="Mês", font=dict(size=14, color='black')),
    yaxis_title=dict(text="Desfolha (%)", font=dict(size=14, color='black')),
    title_font=dict(size=16, family='Arial', color='black'),
    xaxis=dict(tickfont=dict(size=12, color='black')),
    yaxis=dict(tickfont=dict(size=12, color='black')),
    showlegend=False,
    paper_bgcolor='#f5f5f5',
    plot_bgcolor='rgba(0,0,0,0)'
)

# DOWNLOAD GEOPDF

def create_geopdf(mapa, bounds):
    pdf_buffer = io.BytesIO()
    plt.figure(mapa.number) 
    plt.savefig(pdf_buffer, format="pdf", bbox_inches="tight")
    plt.close(mapa)

    writer = PdfWriter()
    pdf_buffer.seek(0)
    reader = PdfReader(pdf_buffer)
    writer.add_page(reader.pages[0])

    metadata = {
        '/Title': 'GeoPDF do Mapa',
        '/Author': 'Combate SF',
        '/Subject': 'GeoPDF com dados geográficos',
        '/Keywords': 'Mapa, GeoPDF, Python',
        '/Geospatial_Coordinates': f'{bounds}',
        '/CRS': 'EPSG:32722',
    }
    writer.add_metadata(metadata)

    final_buffer = io.BytesIO()
    writer.write(final_buffer)
    final_buffer.seek(0)
    return final_buffer


# DOWNLOAD EXCEL

def to_excel(df):
    output = BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df_excel = df.drop(columns = ['Porcentagem', 'Average%'])
        df_excel.to_excel(writer, index=False)
    output.seek(0)  
    return output

# CARD RECOMENDAÇÃO
def create_recommendation_card(title, recommendations):
    rec_items = ''.join([
        f"<li><b>{row['Recomendação']}</b>: {row['Área']:.2f} ha - {row['O que?']}</li>"
        for _, row in recommendations.iterrows()
    ])
    
    return f"""
    <div style="
        background-color: #fdf2e9;
        border-radius: 10px;
        padding: 20px;
        margin: 10px 0;
        box-shadow: 0 4px 8px rgba(0, 0, 0, 0.1);
        font-family: Arial, sans-serif;
        font-size: 18px;
    ">
        <h2 style="color: #d35400; text-align: center;">{title}</h2>
        <ul style="list-style-type: disc; padding-left: 20px; color: #333;">
            {rec_items}
        </ul>
    </div>
    """

# DISPLAY

# Visão geral

st.subheader("Visão geral das fazendas")

col1, col2, col3, col4  = st.columns([1, 1, 1, 1])
with col1: 
    st.markdown(create_card('Área total monitorada (ha)', total_area_ha_rounded), unsafe_allow_html=True)
with col2:
    st.markdown(create_card('Área total em desfolha (ha)', total_area_desfolha_rounded), unsafe_allow_html=True)
with col3:
    st.markdown(create_card('Número total de fazendas', num_unique_farms), unsafe_allow_html=True)
with col4:
    st.markdown(create_card('Número total de talhões', num_unique_stands), unsafe_allow_html=True)

col1, col2, col3 = st.columns([3, 4, 4])
with col1: 
    bg_border('#f5f5f5')
    st.plotly_chart(fig1, use_container_width=True)
with col2:
    bg_border('#f5f5f5')
    st.plotly_chart(fig2, use_container_width=True)
with col3:
    bg_border('#f5f5f5')
    st.plotly_chart(fig3, use_container_width=True)


st.markdown(create_recommendation_card("Recomendações Gerais", recomendacao_geral), unsafe_allow_html=True)

# Informações das fazendas

st.subheader("Informações das fazendas")

col1, col2, col3  = st.columns([1, 1, 1])
with col1: 
    st.markdown(create_card('Área total na fazenda selecionada (ha)',farm_area_ha_rounded), unsafe_allow_html=True)
with col2:
    st.markdown(create_card('Área em desfolha na fazenda (ha)', farm_area_desfolha_rounded), unsafe_allow_html=True)
with col3:
    st.markdown(create_card('Número de talhões na fazenda', num_unique_stands_farm), unsafe_allow_html=True)

col1, col2 = st.columns([1, 1])
with col1:
    bg_border('#f5f5f5')
    st.plotly_chart(fig4, use_container_width=True)
with col2:
    bg_border('#f5f5f5')
    st.plotly_chart(fig5, use_container_width=True)

bg_border('#f5f5f5')
st.plotly_chart(fig9, use_container_width=True)

st.markdown(create_recommendation_card("Recomendações Gerais", recomendacao_farm), unsafe_allow_html=True)


# Informações do talhão

st.subheader('Informações do talhão')

col1, col2, col3, col4 = st.columns([1, 2, 2, 1])
with col2:
    st.markdown(create_card('Área total no talhão selecionado (ha)', stand_area_ha_rounded), unsafe_allow_html=True)
with col3:
    st.markdown(create_card('Área em desfolha no talhão (ha)', stand_area_desfolha_rounded), unsafe_allow_html=True)

col1, col2 = st.columns([1, 1])
with col1:
    bg_border('#f5f5f5')
    st.plotly_chart(fig6, use_container_width=True)
with col2:
    bg_border('#f5f5f5')
    st.plotly_chart(fig10, use_container_width=True)

# Mapas

st.subheader('Mapas')

col1, col2 = st.columns([2, 1])
with col1:
    st.pyplot(fig7)
with col2:
    st.pyplot(fig8)

#  BOTÕES DE DOWNLOAD

# Planilhas de recomendação
st.sidebar.write("**Baixar planilha de recomendação:**")
# Descomentar esse trecho para mostrar a planilha por fazenda
#st.sidebar.download_button(
#    label="Planilha por fazenda",
#    data=to_excel(grouped_farm_excel),
#    file_name='recomendacao_fazenda.csv',
#    mime='text/csv')
st.sidebar.download_button(
    label="Planilha por talhão",
    data=to_excel(grouped_stand_excel),
    file_name='recomendacao_talhao.xlsx',
    mime='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')

# GeoPDFs
st.sidebar.write("Baixar GeoPDF")

bounds_farm = stands_sel.total_bounds
st.sidebar.download_button(
    label="Baixar GeoPDF da fazenda",
    data=create_geopdf(fig7, bounds_farm).getvalue(),
    file_name="fazenda_georreferenciado.pdf",
    mime="application/pdf"
)

bounds_stand = stands_sel.total_bounds
st.sidebar.download_button(
    label="Baixar GeoPDF do talhão",
    data=create_geopdf(fig8, bounds_stand).getvalue(),
    file_name="talhao_georreferenciado.pdf",
    mime="application/pdf"
)
