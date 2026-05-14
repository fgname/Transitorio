import streamlit as st
import pandas as pd
import plotly.express as px
import os
import base64
import io
from datetime import datetime, timedelta
from github import Github

# --- 0. CONFIGURAÇÃO DA PÁGINA ---
st.set_page_config(page_title="Inteligência de Giro - Tecadi", layout="wide", initial_sidebar_state="expanded")

def aplicar_estilo_blindado():
    BG_PATH = "assets/tecadi.png"
    estilo = """
    <style>
    .element-container:has(style) { display: none; }
    [data-testid="stSidebar"] { background-color: #003366 !important; }
    [data-testid="stSidebar"] h3, [data-testid="stSidebar"] label, 
    [data-testid="stSidebar"] p, [data-testid="stSidebar"] .stMarkdownContainer p {
        color: #FFFFFF !important; font-weight: 600 !important;
    }
    [data-testid="stFileUploadDropzone"] span, [data-testid="stFileUploadDropzone"] small,
    [data-testid="stFileUploadDropzone"] p, [data-testid="stFileUploadDropzone"] div {
        color: #000000 !important;
    }
    [data-testid="stSidebar"] input, [data-testid="stSidebar"] div[data-baseweb="select"] span {
        color: #000000 !important;
    }
    .stApp { color: #1E1E1E; }
    h1, h2, h3 { color: #003366 !important; font-weight: bold !important; }
    [data-testid="stMetricLabel"] * { color: #000000 !important; font-weight: bold !important; font-size: 16px !important;}
    [data-testid="stMetricValue"] { color: #003366 !important; font-weight: 900 !important;}
    </style>
    """
    st.markdown(estilo, unsafe_allow_html=True)
    if os.path.exists(BG_PATH):
        with open(BG_PATH, "rb") as f: data = base64.b64encode(f.read()).decode()
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
        
        # AUTOCURA: Se a coluna de controle do último endereço não existir na base antiga, ele cria.
        if 'DT Ultimo Endereco' not in df.columns:
            df['DT Ultimo Endereco'] = df['DT Entrada']
        else:
            df['DT Ultimo Endereco'] = pd.to_datetime(df['DT Ultimo Endereco'], errors='coerce')
            
        return df
    return pd.DataFrame()

def push_to_github():
    try:
        g = Github(st.secrets["GITHUB_TOKEN"])
        repo = g.get_repo(st.secrets["REPO_NAME"])
        with open(HISTORICO_PATH, "rb") as f: content = f.read()
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
        df_hist['DT Ultimo Endereco'] = data_operacao
        df_hist['Endereço Anterior'] = "-"
        df_hist['Qtd Movimentações'] = 0
        df_hist['Status'] = 'Em Trânsito'
        df_hist['Dias Pendentes'] = 0
        df_hist['Dias End. Atual'] = 0
    else:
        df_hist_ativo = df_hist[df_hist['Status'] == 'Em Trânsito'].copy()
        ativos_lista = df_hist_ativo['Serial'].tolist()
        
        df_mantidos = df_atual[df_atual['Serial'].isin(ativos_lista)].copy()
        old_end = df_hist_ativo.set_index('Serial')['Endereço']
        old_mov = df_hist_ativo.set_index('Serial')['Qtd Movimentações']
        old_dt = df_hist_ativo.set_index('Serial')['DT Entrada']
        old_ant = df_hist_ativo.set_index('Serial')['Endereço Anterior']
        old_dt_ult = df_hist_ativo.set_index('Serial')['DT Ultimo Endereco']
        
        df_mantidos['DT Entrada'] = df_mantidos['Serial'].map(old_dt)
        df_mantidos['Endereço Antigo Memoria'] = df_mantidos['Serial'].map(old_end)
        df_mantidos['DT Ultimo Endereco'] = df_mantidos['Serial'].map(old_dt_ult)
        
        mudou_mask = df_mantidos['Endereço'] != df_mantidos['Endereço Antigo Memoria']
        
        # Lógica de atualização quando o serial muda de endereço transitório
        df_mantidos['Endereço Anterior'] = df_mantidos['Serial'].map(old_ant)
        df_mantidos.loc[mudou_mask, 'Endereço Anterior'] = df_mantidos.loc[mudou_mask, 'Endereço Antigo Memoria']
        df_mantidos.loc[mudou_mask, 'DT Ultimo Endereco'] = data_operacao # Reseta o relógio do endereço atual
        
        df_mantidos['Qtd Movimentações'] = df_mantidos['Serial'].map(old_mov).fillna(0)
        df_mantidos.loc[mudou_mask, 'Qtd Movimentações'] += 1
        
        df_mantidos['Status'] = 'Em Trânsito'
        df_mantidos['Dias Pendentes'] = (data_operacao - pd.to_datetime(df_mantidos['DT Entrada'])).dt.days
        df_mantidos['Dias End. Atual'] = (data_operacao - pd.to_datetime(df_mantidos['DT Ultimo Endereco'])).dt.days
        
        df_mantidos = df_mantidos.drop(columns=['Endereço Antigo Memoria'])
        
        df_novos = df_atual[~df_atual['Serial'].isin(ativos_lista)].copy()
        df_novos['DT Entrada'] = data_operacao
        df_novos['DT Ultimo Endereco'] = data_operacao
        df_novos['Endereço Anterior'] = "-"
        df_novos['Qtd Movimentações'] = 0
        df_novos['Status'] = 'Em Trânsito'
        df_novos['Dias Pendentes'] = 0
        df_novos['Dias End. Atual'] = 0
        
        df_saidas = df_hist_ativo[~df_hist_ativo['Serial'].isin(df_atual['Serial'].tolist())].copy()
        df_saidas['Status'] = 'Finalizado'
        df_saidas['DT Saída'] = data_operacao
        
        df_hist = pd.concat([df_hist[df_hist['Status'] == 'Finalizado'], df_saidas, df_mantidos, df_novos], ignore_index=True)

    df_hist.to_parquet(HISTORICO_PATH, index=False)
    return push_to_github()

# --- 2. SIDEBAR ---
with st.sidebar:
    LOGO_PATH = "assets/logosemfundotecadi.png"
    if os.path.exists(LOGO_PATH): st.image(LOGO_PATH, use_container_width=True)
    
    st.markdown("### 🔄 Atualização de Dados")
    
    df_full = load_data()
    ultima_data_banco = None
    
    if not df_full.empty:
        df_pendente_temp = df_full[df_full['Status'] == 'Em Trânsito']
        if not df_pendente_temp.empty:
            ultima_data_banco = (df_pendente_temp['DT Entrada'] + pd.to_timedelta(df_pendente_temp['Dias Pendentes'], unit='d')).max()
        else:
            ultima_data_banco = pd.to_datetime(df_full['DT Saída'], errors='coerce').max()
            
        st.warning(f"📌 **Última base lida: {ultima_data_banco.strftime('%d/%m/%Y')}**")

    data_batimento = st.date_input("Data do Novo Relatório:", value=datetime.today(), format="DD/MM/YYYY")
    arquivo = st.file_uploader("Anexe o Batimento (.xlsx)", type=['xlsx'])
    
    data_ja_processada = False
    if ultima_data_banco and pd.to_datetime(data_batimento) <= ultima_data_banco:
        st.error("⚠️ Esta data já consta no sistema ou é anterior à última atualização.")
        data_ja_processada = True

    if arquivo:
        btn_label = "Sincronizar Retenção" if not data_ja_processada else "Sobrescrever Dados (Cuidado)"
        btn_type = "primary" if not data_ja_processada else "secondary"
        
        if st.button(btn_label, use_container_width=True, type=btn_type):
            with st.spinner("Mapeando histórico..."):
                if processar_motor(arquivo, data_batimento):
                    st.success(f"Base de {data_batimento.strftime('%d/%m/%Y')} atualizada!")
                    st.rerun()

    st.markdown("---")
    df_pendente = df_full[df_full['Status'] == 'Em Trânsito'] if not df_full.empty else pd.DataFrame()
    
    if not df_pendente.empty:
        st.markdown("### 🔍 Filtros")
        f_az = st.selectbox("Filtrar por AZ", ["Todos"] + sorted(df_pendente['AZ'].dropna().unique().tolist()))
        if f_az != "Todos": df_pendente = df_pendente[df_pendente['AZ'] == f_az]

# --- 3. DASHBOARD ---
st.title("📦 Hub de Retenção Transitória")

if df_full.empty:
    st.info("A base está vazia. Informe a data e anexe o primeiro batimento.")
    st.stop()

c1, c2, c3, c4 = st.columns(4)
with c1: st.metric("Seriais no Transitório", len(df_pendente))
with c2: st.metric("Estouro Grave (1+ Dias)", len(df_pendente[df_pendente['Dias Pendentes'] >= 1]))
with c3: st.metric("Movimentados Internamente", len(df_pendente[df_pendente['Qtd Movimentações'] > 0]))
with c4: st.metric("⚠️ Críticos (B110/B116)", len(df_pendente[df_pendente['Prioridade'] == 'CRÍTICO']))

st.markdown("---")

if not df_pendente.empty:
    st.subheader("🔥 Foco de Atuação: Seriais Retidos há 1 Dia ou Mais")
    df_problema = df_pendente[df_pendente['Dias Pendentes'] >= 1]
    
    if not df_problema.empty:
        grafico_problema = df_problema.groupby(['AZ', 'RESPONSAVEL']).size().reset_index(name='Qtd_Retida')
        fig = px.bar(
            grafico_problema, x="AZ", y="Qtd_Retida", color="RESPONSAVEL",
            text_auto=True, template="plotly_white",
            color_discrete_sequence=px.colors.qualitative.Bold
        )
        fig.update_layout(xaxis={'categoryorder':'total descending'})
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.success("🎉 Excelente! Nada retido por mais de 1 dia.")

    st.markdown("---")
    st.subheader("📋 Mapa de Rastreio Operacional")
    
    # Adicionando a nova métrica na visão de detalhe
    df_detalhe = df_pendente[['Serial', 'AZ', 'RESPONSAVEL', 'Prioridade', 'Dias Pendentes', 'Dias End. Atual', 'Qtd Movimentações', 'Endereço', 'Endereço Anterior', 'DT Entrada']].copy()
    
    # Renomeando as colunas, otimizando o espaço conforme o seu padrão
    df_detalhe.rename(columns={
        'Endereço': 'Endereço Atual', 
        'Endereço Anterior': 'End. Anterior', 
        'Qtd Movimentações': 'Mov. Internas', 
        'DT Entrada': 'DT Chegada'
    }, inplace=True)
    
    df_detalhe['DT Chegada'] = df_detalhe['DT Chegada'].dt.strftime('%d/%m/%Y')
    
    # Tabela agora exibe a coluna "Dias End. Atual" logo do lado do total de dias
    st.dataframe(df_detalhe.sort_values(by=["Dias Pendentes", "Mov. Internas"], ascending=False), use_container_width=True, hide_index=True)