import streamlit as st
import pandas as pd
import plotly.express as px
import os
import base64
import io
from datetime import datetime
from github import Github

# --- 0. CONFIGURAÇÃO DA PÁGINA ---
st.set_page_config(page_title="Controle de Giro - Tecadi", layout="wide", initial_sidebar_state="expanded")

def aplicar_estilo_blindado():
    BG_PATH = "assets/tecadi.png"
    
    estilo = """
    <style>
    /* 1. Limpeza */
    .element-container:has(style) { display: none; }

    /* 2. SIDEBAR - Fundo Azul */
    [data-testid="stSidebar"] {
        background-color: #003366 !important;
    }
    
    /* Textos Base da Sidebar em Branco */
    [data-testid="stSidebar"] h3, 
    [data-testid="stSidebar"] label, 
    [data-testid="stSidebar"] p, 
    [data-testid="stSidebar"] .stMarkdownContainer p {
        color: #FFFFFF !important;
        font-weight: 600 !important;
    }

    /* 🔥 CORREÇÃO: Letra PRETA forçada na área de Upload (Drag and Drop) */
    [data-testid="stFileUploadDropzone"] span,
    [data-testid="stFileUploadDropzone"] small,
    [data-testid="stFileUploadDropzone"] p,
    [data-testid="stFileUploadDropzone"] div {
        color: #000000 !important;
    }

    /* 🔥 CORREÇÃO: Letra PRETA forçada dentro dos Inputs (Data e Seleção) */
    [data-testid="stSidebar"] input {
        color: #000000 !important;
    }
    [data-testid="stSidebar"] div[data-baseweb="select"] span {
        color: #000000 !important;
    }

    /* 3. CONTEÚDO PRINCIPAL (Letras Escuras) */
    .stApp { color: #1E1E1E; }
    h1, h2, h3 { color: #003366 !important; font-weight: bold !important; }
    
    /* Letra PRETA nos títulos dos KPIs */
    [data-testid="stMetricLabel"] * {
        color: #000000 !important;
        font-weight: bold !important;
    }
    [data-testid="stMetricValue"] {
        color: #003366 !important;
    }
    </style>
    """
    st.markdown(estilo, unsafe_allow_html=True)

    if os.path.exists(BG_PATH):
        with open(BG_PATH, "rb") as f:
            data = base64.b64encode(f.read()).decode()
        st.markdown(f"""<style>.stApp {{ background-image: url("data:image/png;base64,{data}"); background-size: cover; background-attachment: fixed; }}</style>""", unsafe_allow_html=True)

aplicar_estilo_blindado()

# --- 1. MOTOR DE DADOS ---
HISTORICO_PATH = "historico_seriais.parquet"
ENDERECOS_PATH = "Endereços Transitorios.xlsx"

@st.cache_data(ttl=60)
def load_data():
    if os.path.exists(HISTORICO_PATH):
        df = pd.read_parquet(HISTORICO_PATH)
        df['DT Entrada'] = pd.to_datetime(df['DT Entrada'], errors='coerce')
        return df
    return pd.DataFrame()

def push_to_github():
    try:
        g = Github(st.secrets["GITHUB_TOKEN"])
        repo = g.get_repo(st.secrets["REPO_NAME"])
        with open(HISTORICO_PATH, "rb") as f:
            content = f.read()
        try:
            contents = repo.get_contents(HISTORICO_PATH, ref="main")
            repo.update_file(contents.path, f"Sinc: {datetime.now().strftime('%d/%m/%Y %H:%M')}", content, contents.sha, branch="main")
        except:
            repo.create_file(HISTORICO_PATH, "Base Inicial", content, branch="main")
        return True
    except Exception as e:
        st.error(f"Erro GitHub: {e}")
        return False

def processar_motor(arquivo_novo, data_selecionada):
    df_batimento = pd.read_excel(arquivo_novo, skiprows=6)
    df_enderecos = pd.read_excel(ENDERECOS_PATH)
    df_batimento.rename(columns={'Data doc': 'DT Doc', 'Data Serial': 'DT Serial'}, inplace=True)
    df_atual = pd.merge(df_batimento, df_enderecos, left_on='Endereço', right_on='ENDEREÇO', how='inner')
    
    def set_prioridade(row):
        criticos = ['B110', 'B116']
        for col in ['Tp.Estoque Midea', 'Subestoque Midea', 'Tp.Estoque Tecadi', 'Subestoque Tecadi']:
            if row.get(col) in criticos: return 'CRÍTICO'
        return 'Normal'
    
    df_atual['Prioridade'] = df_atual.apply(set_prioridade, axis=1)
    data_operacao = pd.to_datetime(data_selecionada)
    df_hist = load_data()

    if df_hist.empty:
        df_hist = df_atual.copy()
        df_hist['DT Entrada'] = data_operacao
        df_hist['Status'] = 'Em Trânsito'
        df_hist['Dias Pendentes'] = 0
    else:
        df_hist_ativo = df_hist[df_hist['Status'] == 'Em Trânsito'].copy()
        df_hist_ativo['Chave'] = df_hist_ativo['Serial'].astype(str) + df_hist_ativo['Endereço'].astype(str)
        df_atual['Chave'] = df_atual['Serial'].astype(str) + df_atual['Endereço'].astype(str)
        
        df_mantidos = df_atual[df_atual['Chave'].isin(df_hist_ativo['Chave'])].copy()
        entrada_map = df_hist_ativo.set_index('Chave')['DT Entrada'].to_dict()
        df_mantidos['DT Entrada'] = df_mantidos['Chave'].map(entrada_map)
        df_mantidos['Status'] = 'Em Trânsito'
        df_mantidos['Dias Pendentes'] = (data_operacao - pd.to_datetime(df_mantidos['DT Entrada'])).dt.days
        
        df_novos = df_atual[~df_atual['Chave'].isin(df_hist_ativo['Chave'])].copy()
        df_novos['DT Entrada'] = data_operacao
        df_novos['Status'] = 'Em Trânsito'
        df_novos['Dias Pendentes'] = 0
        
        df_saidas = df_hist_ativo[~df_hist_ativo['Chave'].isin(df_atual['Chave'])].copy()
        df_saidas['Status'] = 'Finalizado'
        df_saidas['DT Saída'] = data_operacao
        
        df_hist = pd.concat([df_hist[df_hist['Status'] == 'Finalizado'], df_saidas, df_mantidos, df_novos], ignore_index=True)

    df_hist.to_parquet(HISTORICO_PATH, index=False)
    return push_to_github()

# --- 2. SIDEBAR ---
with st.sidebar:
    LOGO_PATH = "assets/logosemfundotecadi.png"
    if os.path.exists(LOGO_PATH):
        st.image(LOGO_PATH, use_container_width=True)
    
    st.markdown("### Atualização Diária")
    
    # 🔥 DATA SETADA PARA PADRÃO PT-BR (DD/MM/YYYY)
    data_batimento = st.date_input(
        "Data Oficial do Relatório:", 
        value=datetime.today(),
        format="DD/MM/YYYY" # Isso seta o padrão visual do widget
    )
    
    arquivo = st.file_uploader("Suba o Batimento", type=['xlsx'])
    
    if arquivo and st.button("Processar Dados", use_container_width=True, type="primary"):
        with st.spinner("Processando..."):
            if processar_motor(arquivo, data_batimento):
                st.success(f"Base de {data_batimento.strftime('%d/%m/%Y')} atualizada!")
                st.rerun()

    st.markdown("---")
    df_full = load_data()
    df_pendente = df_full[df_full['Status'] == 'Em Trânsito'] if not df_full.empty else pd.DataFrame()
    
    if not df_pendente.empty:
        st.markdown("### Filtros")
        f_az = st.selectbox("Filtrar AZ", ["Todos"] + sorted(df_pendente['AZ'].dropna().unique().tolist()))
        if f_az != "Todos": 
            df_pendente = df_pendente[df_pendente['AZ'] == f_az]

# --- 3. DASHBOARD ---
st.title("📦 Controle de Giro de Seriais")

if df_full.empty:
    st.info("Aguardando o upload do primeiro arquivo para iniciar o BI.")
    st.stop()

# KPIs (Títulos agora em PRETO)
c1, c2, c3 = st.columns(3)
with c1: st.metric("Saldo Ativo", len(df_pendente))
with c2: st.metric("Prioridade (B110/B116)", len(df_pendente[df_pendente['Prioridade'] == 'CRÍTICO']))
with c3: st.metric("Estouro SLA (>48h)", len(df_pendente[df_pendente['Dias Pendentes'] >= 2]))

st.markdown("---")

if not df_pendente.empty:
    # --- GRÁFICO POR AZ (EM PRIMEIRO LUGAR) ---
    st.subheader("📊 Gráfico de Volume por AZ e Responsável")
    
    resumo_grafico = df_pendente.groupby(['AZ', 'RESPONSAVEL']).size().reset_index(name='Quantidade')
    resumo_grafico = resumo_grafico.sort_values('Quantidade', ascending=False)
    
    fig = px.bar(
        resumo_grafico, x="AZ", y="Quantidade", color="RESPONSAVEL",
        text_auto=True, template="plotly_white",
        color_discrete_sequence=px.colors.qualitative.Safe
    )
    fig.update_layout(xaxis={'categoryorder':'total descending'}, legend_title_text='Responsável')
    st.plotly_chart(fig, use_container_width=True)

    # --- TABELAS ---
    st.markdown("---")
    st.subheader("📋 Detalhamento Operacional")
    
    aba1, aba2 = st.tabs(["📋 Resumo por AZ", "🔍 Visão por Serial"])
    with aba1:
        st.dataframe(resumo_grafico, use_container_width=True, hide_index=True)
    with aba2:
        df_detalhe = df_pendente[['Serial', 'Endereço', 'AZ', 'RESPONSAVEL', 'Prioridade', 'Dias Pendentes']].sort_values("Dias Pendentes", ascending=False)
        st.dataframe(df_detalhe, use_container_width=True, hide_index=True)

    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
        df_detalhe.to_excel(writer, index=False, sheet_name='Giro_Tecadi')
    
    st.download_button(
        label="📥 Baixar Relatório em Excel",
        data=buffer.getvalue(),
        file_name=f"Giro_AZ_{datetime.now().strftime('%d%m%Y')}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        type="primary"
    )