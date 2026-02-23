from flask import Flask, render_template, request, jsonify, send_file
import sqlite3, json, os, re, math
from datetime import datetime
import urllib.request, urllib.error

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

app = Flask(
    __name__,
    template_folder=os.path.join(BASE_DIR, 'templates'),
    static_folder=os.path.join(BASE_DIR, 'static'),
)

# No Render o disco persistente fica em /data.
# Localmente (Windows/Linux) usa a pasta db/ do projeto.
if os.environ.get('RENDER') and os.path.isdir('/data'):
    DATA_DIR = '/data'
else:
    DATA_DIR = os.path.join(BASE_DIR, 'db')

DB_DIR  = DATA_DIR
DB_PATH = os.path.join(DATA_DIR, 'credito.db')

# ─────────────────────────────────────────
# DATABASE
# ─────────────────────────────────────────
def get_db():
    os.makedirs(DB_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn

def init_db():
    from datetime import datetime
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    conn = get_db()
    cur  = conn.cursor()

    cur.executescript("""
        PRAGMA journal_mode=WAL;
        PRAGMA foreign_keys=ON;

        CREATE TABLE IF NOT EXISTS consultas (
            id                    INTEGER PRIMARY KEY AUTOINCREMENT,
            cnpj                  TEXT NOT NULL,
            razao_social          TEXT,
            nome_fantasia         TEXT,
            valor_solicitado      REAL,
            parcelas              INTEGER,
            juros                 REAL,
            score_empresa         INTEGER,
            score_controladores   INTEGER,
            valor_sugerido        REAL,
            risco                 TEXT,
            situacao_cadastral    TEXT,
            porte_empresa         TEXT,
            natureza_juridica     TEXT,
            capital_social        TEXT,
            data_inicio_atividade TEXT,
            municipio             TEXT,
            uf                    TEXT,
            email                 TEXT,
            cnae_principal        TEXT,
            faturamento_declarado REAL,
            setor                 TEXT,
            finalidade            TEXT,
            garantias             TEXT,
            observacoes           TEXT,
            num_socios            INTEGER DEFAULT 0,
            num_processos         INTEGER DEFAULT 0,
            dados_json            TEXT,
            relatorio_path        TEXT,
            created_at            TEXT,
            updated_at            TEXT
        );

        CREATE TABLE IF NOT EXISTS socios (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            consulta_id   INTEGER NOT NULL,
            nome          TEXT,
            cpf_cnpj      TEXT,
            qualificacao  TEXT,
            data_entrada  TEXT,
            faixa_etaria  TEXT,
            identificador TEXT,
            FOREIGN KEY (consulta_id) REFERENCES consultas(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS processos (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            consulta_id      INTEGER NOT NULL,
            numero           TEXT,
            tribunal         TEXT,
            classe           TEXT,
            assunto          TEXT,
            data_ajuizamento TEXT,
            situacao         TEXT,
            valor_causa      REAL,
            partes           TEXT,
            FOREIGN KEY (consulta_id) REFERENCES consultas(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS api_config (
            key        TEXT PRIMARY KEY,
            label      TEXT,
            descricao  TEXT,
            enabled    INTEGER DEFAULT 1,
            api_key    TEXT DEFAULT '',
            updated_at TEXT
        );

        CREATE TABLE IF NOT EXISTS api_logs (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            consulta_id      INTEGER,
            api_name         TEXT,
            endpoint         TEXT,
            status           TEXT,
            response_time_ms INTEGER,
            error            TEXT,
            created_at       TEXT
        );

        CREATE TABLE IF NOT EXISTS relatorios (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            consulta_id   INTEGER NOT NULL UNIQUE,
            pdf_path      TEXT,
            tamanho_bytes INTEGER,
            gerado_em     TEXT,
            FOREIGN KEY (consulta_id) REFERENCES consultas(id) ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS idx_consultas_cnpj     ON consultas(cnpj);
        CREATE INDEX IF NOT EXISTS idx_consultas_risco    ON consultas(risco);
        CREATE INDEX IF NOT EXISTS idx_consultas_created  ON consultas(created_at);
        CREATE INDEX IF NOT EXISTS idx_socios_consulta    ON socios(consulta_id);
        CREATE INDEX IF NOT EXISTS idx_processos_consulta ON processos(consulta_id);
        CREATE INDEX IF NOT EXISTS idx_logs_consulta      ON api_logs(consulta_id);
        CREATE INDEX IF NOT EXISTS idx_logs_api           ON api_logs(api_name);
    """)

    apis = [
        ("opencnpj",   "OpenCNPJ",         "api.opencnpj.org — dados cadastrais gratuitos",                1, ""),
        ("brasilapi",  "Brasil API",        "brasilapi.com.br — CNPJ e dados públicos",                     1, ""),
        ("dadosgov",   "Dados.gov.br",      "Portal de dados abertos do governo federal",                   1, ""),
        ("invertexto", "InverTexto",        "api.invertexto.com — dados enriquecidos (requer key)",          0, ""),
        ("cnpja",      "CNPJa",             "cnpja.com — dados completos e processos (requer key)",          0, ""),
        ("datajud",    "DataJud CNJ",       "Processos judiciais nacionais — requer token CNJ",              0, ""),
        ("anthropic",  "Anthropic Claude",  "IA para análise completa do relatório (requer API key)",        0, ""),
        ("perplexity", "Perplexity AI",     "Busca web em tempo real + análise de reputação (requer key)",  1, ""),
    ]
    for a in apis:
        cur.execute(
            "INSERT OR IGNORE INTO api_config (key, label, descricao, enabled, api_key, updated_at) VALUES (?,?,?,?,?,?)",
            (*a, now)
        )

    conn.commit()
    conn.close()

init_db()

# ─────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────
def get_api_config():
    conn = get_db()
    rows = conn.execute("SELECT key, label, descricao, enabled, api_key FROM api_config").fetchall()
    conn.close()
    return {
        r['key']: {
            'enabled':   bool(r['enabled']),
            'api_key':   r['api_key'] or '',
            'label':     r['label'] or r['key'],
            'descricao': r['descricao'] or '',
        }
        for r in rows
    }

def fetch_url(url, headers=None, timeout=10):
    try:
        req = urllib.request.Request(url, headers=headers or {'User-Agent': 'CreditoApp/1.0'})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode())
    except Exception as e:
        return {'error': str(e)}

def clean_cnpj(cnpj):
    return re.sub(r'\D', '', cnpj)

# ─────────────────────────────────────────
# DATA FETCHERS
# ─────────────────────────────────────────
def fetch_opencnpj(cnpj, cfg):
    if not cfg.get('opencnpj', {}).get('enabled'):
        return {}
    data = fetch_url(f"https://api.opencnpj.org/{cnpj}")
    return data if 'error' not in data else {}

def fetch_brasilapi(cnpj, cfg):
    if not cfg.get('brasilapi', {}).get('enabled'):
        return {}
    data = fetch_url(f"https://brasilapi.com.br/api/cnpj/v1/{cnpj}")
    return data if 'error' not in data else {}

def fetch_cnpja(cnpj, cfg):
    if not cfg.get('cnpja', {}).get('enabled'):
        return {}
    key = cfg['cnpja'].get('api_key', '')
    if not key:
        return {}
    data = fetch_url(f"https://api.cnpja.com/office/{cnpj}", headers={'Authorization': key})
    return data if 'error' not in data else {}

def fetch_invertexto(cnpj, cfg):
    if not cfg.get('invertexto', {}).get('enabled'):
        return {}
    key = cfg['invertexto'].get('api_key', '')
    if not key:
        return {}
    data = fetch_url(f"https://api.invertexto.com/v1/cnpj/{cnpj}?token={key}")
    return data if 'error' not in data else {}

def fetch_datajud(nome_empresa, cfg):
    if not cfg.get('datajud', {}).get('enabled'):
        return {}
    # DataJud CNJ public API
    url = f"https://api-publica.datajud.cnj.jus.br/api_publica_tjsp/_search"
    # Returns process data - simplified query
    try:
        query = json.dumps({"query": {"match": {"partes.nome": nome_empresa}}, "size": 10})
        req = urllib.request.Request(url, data=query.encode(), 
            headers={'Content-Type': 'application/json', 'User-Agent': 'CreditoApp/1.0'})
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode())
    except:
        return {}

def merge_company_data(opencnpj_data, brasilapi_data, cnpja_data):
    """Merge all sources, opencnpj takes priority"""
    merged = {}
    for src in [brasilapi_data, cnpja_data, opencnpj_data]:
        merged.update({k: v for k, v in src.items() if v})
    return merged

# ─────────────────────────────────────────
# SCORING ENGINE
# ─────────────────────────────────────────
def calculate_score(company_data, judicial_data, social_data, valor_solicitado, capital_social):
    score = 50  # base
    reasons = []

    # Situação cadastral
    situacao = str(company_data.get('situacao_cadastral', '')).lower()
    if 'ativa' in situacao:
        score += 15
        reasons.append(('✓', 'Empresa ativa na Receita Federal', +15))
    else:
        score -= 25
        reasons.append(('✗', f'Situação cadastral irregular: {situacao}', -25))

    # Tempo de empresa
    try:
        inicio = company_data.get('data_inicio_atividade', '') or company_data.get('abertura', '')
        if inicio:
            ano = int(str(inicio)[:4])
            anos = datetime.now().year - ano
            if anos >= 10:
                score += 15
                reasons.append(('✓', f'Empresa com {anos} anos de atividade', +15))
            elif anos >= 5:
                score += 8
                reasons.append(('~', f'Empresa com {anos} anos de atividade', +8))
            elif anos < 2:
                score -= 10
                reasons.append(('✗', f'Empresa jovem ({anos} anos)', -10))
    except:
        pass

    # Capital social vs valor solicitado
    try:
        cap_str = str(capital_social or company_data.get('capital_social', '0'))
        cap = float(re.sub(r'[^\d.,]', '', cap_str).replace(',', '.'))
        if cap > 0 and valor_solicitado > 0:
            ratio = cap / valor_solicitado
            if ratio >= 2:
                score += 12
                reasons.append(('✓', f'Capital social ({cap:,.2f}) sólido vs valor solicitado', +12))
            elif ratio >= 0.5:
                score += 5
                reasons.append(('~', f'Capital social adequado em relação ao crédito', +5))
            else:
                score -= 8
                reasons.append(('✗', 'Capital social baixo para o crédito solicitado', -8))
    except:
        pass

    # Porte
    porte = str(company_data.get('porte_empresa', '') or company_data.get('porte', '')).lower()
    if 'grande' in porte:
        score += 10
        reasons.append(('✓', 'Grande empresa', +10))
    elif 'medio' in porte or 'média' in porte:
        score += 5
        reasons.append(('~', 'Empresa de médio porte', +5))
    elif 'micro' in porte or 'mei' in porte:
        score -= 3
        reasons.append(('~', 'Microempresa/MEI', -3))

    # Processos judiciais
    proc_count = 0
    if isinstance(judicial_data, dict):
        hits = judicial_data.get('hits', {})
        if isinstance(hits, dict):
            proc_count = hits.get('total', {}).get('value', 0) if isinstance(hits.get('total'), dict) else int(hits.get('total', 0))
    if proc_count > 10:
        score -= 20
        reasons.append(('✗', f'{proc_count} processos judiciais encontrados', -20))
    elif proc_count > 3:
        score -= 10
        reasons.append(('~', f'{proc_count} processos judiciais encontrados', -10))
    elif proc_count > 0:
        score -= 3
        reasons.append(('~', f'{proc_count} processo(s) judicial(is) encontrado(s)', -3))
    else:
        score += 8
        reasons.append(('✓', 'Nenhum processo judicial identificado', +8))

    # Social media issues
    if social_data.get('controversias'):
        score -= 10
        reasons.append(('✗', 'Controvérsias identificadas nas redes sociais', -10))

    score = max(0, min(100, score))
    
    # Risk level
    if score >= 75:
        risco = 'BAIXO'
        risco_color = '#10b981'
    elif score >= 50:
        risco = 'MÉDIO'
        risco_color = '#f59e0b'
    elif score >= 30:
        risco = 'ALTO'
        risco_color = '#ef4444'
    else:
        risco = 'MUITO ALTO'
        risco_color = '#dc2626'

    # Suggested value
    if score >= 75:
        mult = 1.0
    elif score >= 60:
        mult = 0.8
    elif score >= 45:
        mult = 0.5
    elif score >= 30:
        mult = 0.25
    else:
        mult = 0.0

    valor_sugerido = round(valor_solicitado * mult, 2)

    return {
        'score': score,
        'risco': risco,
        'risco_color': risco_color,
        'valor_sugerido': valor_sugerido,
        'multiplicador': mult,
        'reasons': reasons
    }

# ─────────────────────────────────────────
# AI ANALYSIS
# ─────────────────────────────────────────

AI_PROMPT = """Você é um analista de crédito sênior especializado em empresas brasileiras.

Com base nos dados abaixo, faça uma análise detalhada e profissional:

DADOS DA EMPRESA:
{company_json}

PROCESSOS JUDICIAIS:
{judicial_json}

PESQUISA WEB / REPUTAÇÃO:
{web_research}

SCORE CALCULADO: {score}/100 — Risco: {risco}
VALOR SUGERIDO: R$ {valor_sugerido}

Forneça obrigatoriamente cada uma das seções abaixo:

1. PERFIL DA EMPRESA
Descreva o porte, setor, tempo de mercado, estrutura societária e histórico geral.

2. ANÁLISE DOS SÓCIOS E CONTROLADORES
Avalie cada sócio: histórico, participação, faixa etária, qualificação e eventuais riscos pessoais.

3. RISCOS IDENTIFICADOS
Liste os principais riscos encontrados (judiciais, financeiros, reputacionais, setoriais).

4. PONTOS POSITIVOS
Liste os fatores que favorecem a concessão do crédito.

5. REPUTAÇÃO E PRESENÇA DIGITAL
Com base na pesquisa web, descreva como a empresa aparece publicamente, notícias relevantes e polêmicas.

6. RECOMENDAÇÃO FINAL
Seja direto: recomendar ou não o crédito, qual valor e quais condições/garantias sugerir.

Use linguagem profissional, clara e objetiva em português brasileiro."""


def fetch_perplexity_research(company_name, cnpj, cfg):
    """Usa a Perplexity para pesquisa web em tempo real sobre a empresa."""
    plex_cfg = cfg.get('perplexity', {})
    if not plex_cfg.get('enabled'):
        return None

    key = plex_cfg.get('api_key', '') or os.environ.get('PERPLEXITY_API_KEY', '')
    if not key:
        return None

    queries = [
        f'"{company_name}" CNPJ {cnpj} notícias recentes problemas dívidas',
        f'"{company_name}" processos judiciais falência recuperação judicial',
        f'"{company_name}" reputação reclamações Reclame Aqui avaliações',
    ]

    results = []
    for q in queries:
        try:
            payload = json.dumps({
                "model": "sonar",
                "messages": [
                    {
                        "role": "system",
                        "content": "Você é um pesquisador financeiro. Busque e resuma informações relevantes sobre empresas brasileiras. Seja objetivo e cite fontes."
                    },
                    {
                        "role": "user",
                        "content": f"Pesquise na web: {q}\n\nResuma os resultados mais relevantes encontrados, incluindo datas e fontes."
                    }
                ],
                "max_tokens": 800,
                "search_recency_filter": "month",
                "return_citations": True,
            }).encode()

            req = urllib.request.Request(
                "https://api.perplexity.ai/chat/completions",
                data=payload,
                headers={
                    "Authorization": f"Bearer {key}",
                    "Content-Type": "application/json",
                    "User-Agent": "CreditoIA/1.0",
                }
            )
            with urllib.request.urlopen(req, timeout=20) as resp:
                data = json.loads(resp.read().decode())
                text = data.get('choices', [{}])[0].get('message', {}).get('content', '')
                if text:
                    results.append(f"[Busca: {q}]\n{text}")
        except Exception as e:
            results.append(f"[Busca falhou: {q}] Erro: {str(e)}")

    return "\n\n---\n\n".join(results) if results else None


def ai_analyze(company_data, judicial_data, social_data, cfg, score_result):
    """
    Tenta Perplexity primeiro (pesquisa web em tempo real),
    depois usa Anthropic ou Perplexity para gerar a análise final.
    Retorna (texto_analise, ia_usada).
    """
    company_name = company_data.get('razao_social', '')
    cnpj         = company_data.get('cnpj', '')

    # ── 1. Pesquisa web com Perplexity ──────────────────────────
    web_research = fetch_perplexity_research(company_name, cnpj, cfg)
    if not web_research:
        web_research = (
            "Pesquisa web não realizada "
            "(Perplexity desabilitada ou sem chave configurada)."
        )

    prompt = AI_PROMPT.format(
        company_json  = json.dumps(company_data,  ensure_ascii=False, indent=2)[:3000],
        judicial_json = json.dumps(judicial_data, ensure_ascii=False, indent=2)[:1000],
        web_research  = web_research[:2000],
        score         = score_result['score'],
        risco         = score_result['risco'],
        valor_sugerido= f"{score_result['valor_sugerido']:,.2f}",
    )

    # ── 2a. Análise final com Anthropic ─────────────────────────
    ant_cfg = cfg.get('anthropic', {})
    if ant_cfg.get('enabled'):
        ant_key = ant_cfg.get('api_key', '') or os.environ.get('ANTHROPIC_API_KEY', '')
        if ant_key:
            try:
                import anthropic as ant_sdk
                client = ant_sdk.Anthropic(api_key=ant_key)
                msg = client.messages.create(
                    model="claude-sonnet-4-20250514",
                    max_tokens=2500,
                    messages=[{"role": "user", "content": prompt}]
                )
                return msg.content[0].text, "Anthropic Claude"
            except Exception as e:
                pass  # cai para Perplexity

    # ── 2b. Análise final com Perplexity (fallback) ──────────────
    plex_cfg = cfg.get('perplexity', {})
    if plex_cfg.get('enabled'):
        plex_key = plex_cfg.get('api_key', '') or os.environ.get('PERPLEXITY_API_KEY', '')
        if plex_key:
            try:
                payload = json.dumps({
                    "model": "sonar-pro",
                    "messages": [
                        {"role": "system", "content": "Você é um analista de crédito sênior especializado em empresas brasileiras."},
                        {"role": "user",   "content": prompt}
                    ],
                    "max_tokens": 2500,
                }).encode()

                req = urllib.request.Request(
                    "https://api.perplexity.ai/chat/completions",
                    data=payload,
                    headers={
                        "Authorization": f"Bearer {plex_key}",
                        "Content-Type":  "application/json",
                        "User-Agent":    "CreditoIA/1.0",
                    }
                )
                with urllib.request.urlopen(req, timeout=30) as resp:
                    data = json.loads(resp.read().decode())
                    text = data.get('choices', [{}])[0].get('message', {}).get('content', '')
                    if text:
                        return text, "Perplexity AI"
            except Exception as e:
                return f"Análise IA indisponível: {str(e)}", "Erro"

    return (
        "Nenhuma IA configurada. Acesse Configurações de API e insira a chave "
        "da Anthropic ou da Perplexity para gerar a análise automática.",
        "N/A"
    )

# ─────────────────────────────────────────
# PDF REPORT GENERATOR
# ─────────────────────────────────────────
def generate_pdf(consulta_id, company_data, score_result, ai_analysis, valor_solicitado, parcelas, juros):
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.units import cm
        from reportlab.lib import colors
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
        from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
        import io

        pdf_path = os.path.join(BASE_DIR, 'db', f'relatorio_{consulta_id}.pdf')
        doc = SimpleDocTemplate(pdf_path, pagesize=A4,
            leftMargin=2*cm, rightMargin=2*cm, topMargin=2*cm, bottomMargin=2*cm)

        story = []
        styles = getSampleStyleSheet()
        
        # Custom styles
        title_style = ParagraphStyle('Title', parent=styles['Title'],
            fontSize=24, textColor=colors.HexColor('#0f172a'),
            spaceAfter=6, fontName='Helvetica-Bold')
        h2_style = ParagraphStyle('H2', parent=styles['Heading2'],
            fontSize=14, textColor=colors.HexColor('#1e40af'),
            spaceBefore=16, spaceAfter=8, fontName='Helvetica-Bold')
        body_style = ParagraphStyle('Body', parent=styles['Normal'],
            fontSize=10, leading=16, textColor=colors.HexColor('#374151'))
        small_style = ParagraphStyle('Small', parent=styles['Normal'],
            fontSize=8, textColor=colors.HexColor('#6b7280'))

        # HEADER
        story.append(Paragraph("RELATÓRIO DE ANÁLISE DE CRÉDITO", title_style))
        story.append(Paragraph(f"Emitido em {datetime.now().strftime('%d/%m/%Y às %H:%M')}", small_style))
        story.append(HRFlowable(width="100%", thickness=2, color=colors.HexColor('#1e40af')))
        story.append(Spacer(1, 0.5*cm))

        # EMPRESA INFO
        story.append(Paragraph("1. IDENTIFICAÇÃO DA EMPRESA", h2_style))
        razao = company_data.get('razao_social', 'N/D')
        fantasia = company_data.get('nome_fantasia', '')
        cnpj = company_data.get('cnpj', '')
        
        info_data = [
            ['Razão Social', razao],
            ['Nome Fantasia', fantasia or '—'],
            ['CNPJ', cnpj],
            ['Situação', company_data.get('situacao_cadastral', 'N/D')],
            ['Porte', company_data.get('porte_empresa', company_data.get('porte', 'N/D'))],
            ['Natureza Jurídica', company_data.get('natureza_juridica', 'N/D')],
            ['Município/UF', f"{company_data.get('municipio', '')} / {company_data.get('uf', '')}"],
            ['Capital Social', f"R$ {company_data.get('capital_social', 'N/D')}"],
            ['Início Atividade', company_data.get('data_inicio_atividade', company_data.get('abertura', 'N/D'))],
            ['CNAE Principal', company_data.get('cnae_principal', company_data.get('cnae_fiscal', 'N/D'))],
        ]
        
        t = Table(info_data, colWidths=[5*cm, 12*cm])
        t.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (0,-1), colors.HexColor('#f1f5f9')),
            ('TEXTCOLOR', (0,0), (0,-1), colors.HexColor('#1e40af')),
            ('FONTNAME', (0,0), (0,-1), 'Helvetica-Bold'),
            ('FONTSIZE', (0,0), (-1,-1), 9),
            ('PADDING', (0,0), (-1,-1), 6),
            ('ROWBACKGROUNDS', (1,0), (1,-1), [colors.white, colors.HexColor('#f8fafc')]),
            ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#e2e8f0')),
            ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ]))
        story.append(t)

        # CRÉDITO SOLICITADO
        story.append(Spacer(1, 0.5*cm))
        story.append(Paragraph("2. CRÉDITO SOLICITADO", h2_style))
        
        # Calculate monthly payment
        monthly = 0
        if parcelas and juros and valor_solicitado:
            r = juros / 100
            if r > 0:
                monthly = valor_solicitado * r * (1+r)**parcelas / ((1+r)**parcelas - 1)
            else:
                monthly = valor_solicitado / parcelas
        
        cred_data = [
            ['Valor Solicitado', f"R$ {valor_solicitado:,.2f}"],
            ['Parcelas', f"{parcelas}x"],
            ['Taxa de Juros', f"{juros}% a.m."],
            ['Parcela Estimada', f"R$ {monthly:,.2f}"],
            ['Total a Pagar', f"R$ {monthly * parcelas:,.2f}"],
        ]
        t2 = Table(cred_data, colWidths=[5*cm, 12*cm])
        t2.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (0,-1), colors.HexColor('#f1f5f9')),
            ('TEXTCOLOR', (0,0), (0,-1), colors.HexColor('#1e40af')),
            ('FONTNAME', (0,0), (0,-1), 'Helvetica-Bold'),
            ('FONTSIZE', (0,0), (-1,-1), 9),
            ('PADDING', (0,0), (-1,-1), 6),
            ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#e2e8f0')),
            ('ROWBACKGROUNDS', (1,0), (1,-1), [colors.white, colors.HexColor('#f8fafc')]),
        ]))
        story.append(t2)

        # SCORE CHART
        story.append(Spacer(1, 0.5*cm))
        story.append(Paragraph("3. SCORE DE RISCO", h2_style))

        # Generate matplotlib gauge chart
        fig, ax = plt.subplots(figsize=(6, 3), subplot_kw={'projection': 'polar'})
        score = score_result['score']
        
        # Create gauge
        fig2, (ax1, ax2) = plt.subplots(1, 2, figsize=(10, 4))
        
        # Score gauge
        theta = score / 100 * math.pi
        colors_gauge = ['#ef4444', '#f97316', '#eab308', '#84cc16', '#10b981']
        for i, c in enumerate(colors_gauge):
            ax1.bar(0, 1, bottom=0, color=c, alpha=0.8, width=0.8)
        
        ax1.set_xlim(-1.5, 1.5)
        ax1.set_ylim(-0.2, 1.2)
        ax1.set_aspect('equal')
        ax1.axis('off')
        
        # Draw semicircle gauge properly
        ax1.clear()
        for i in range(100):
            ang = math.pi - (i/100)*math.pi
            ang_next = math.pi - ((i+1)/100)*math.pi
            c_idx = min(int(i/25), 3)
            c = ['#ef4444','#f97316','#eab308','#10b981'][c_idx]
            x = [0, math.cos(ang)*0.9, math.cos(ang_next)*0.9, 0]
            y = [0, math.sin(ang)*0.9, math.sin(ang_next)*0.9, 0]
            ax1.fill(x, y, color=c, alpha=0.7)
        
        # Needle
        needle_ang = math.pi - (score/100)*math.pi
        ax1.plot([0, math.cos(needle_ang)*0.75], [0, math.sin(needle_ang)*0.75], 
                 'k-', linewidth=3, solid_capstyle='round')
        ax1.plot(0, 0, 'ko', markersize=8)
        ax1.text(0, -0.15, f'{score}/100', ha='center', va='center', fontsize=16, fontweight='bold')
        ax1.text(0, -0.32, score_result['risco'], ha='center', va='center', fontsize=12,
                 color=score_result['risco_color'], fontweight='bold')
        ax1.text(-0.95, -0.1, 'MUITO\nALTO', ha='center', fontsize=7, color='#ef4444')
        ax1.text(0.95, -0.1, 'BAIXO', ha='center', fontsize=7, color='#10b981')
        ax1.set_xlim(-1.2, 1.2); ax1.set_ylim(-0.5, 1.1)
        ax1.axis('off')
        ax1.set_title('Score da Empresa', fontsize=11, fontweight='bold', pad=10)

        # Reasons bar chart
        reasons = score_result.get('reasons', [])
        labels = [r[1][:35]+'...' if len(r[1])>35 else r[1] for r in reasons[:8]]
        values = [r[2] for r in reasons[:8]]
        bar_colors = ['#10b981' if v > 0 else '#ef4444' for v in values]
        bars = ax2.barh(range(len(labels)), values, color=bar_colors, alpha=0.8)
        ax2.set_yticks(range(len(labels)))
        ax2.set_yticklabels(labels, fontsize=7)
        ax2.axvline(0, color='black', linewidth=0.8)
        ax2.set_title('Fatores de Avaliação', fontsize=11, fontweight='bold')
        ax2.set_xlabel('Impacto no Score')
        
        plt.tight_layout()
        img_buf = io.BytesIO()
        plt.savefig(img_buf, format='PNG', dpi=150, bbox_inches='tight')
        img_buf.seek(0)
        plt.close()

        from reportlab.platypus import Image as RLImage
        img = RLImage(img_buf, width=17*cm, height=7*cm)
        story.append(img)
        story.append(Spacer(1, 0.3*cm))

        # Score table
        score_table = [
            ['Score Final', f"{score}/100"],
            ['Nível de Risco', score_result['risco']],
            ['Valor Solicitado', f"R$ {valor_solicitado:,.2f}"],
            ['Valor Sugerido', f"R$ {score_result['valor_sugerido']:,.2f}"],
            ['Percentual Aprovado', f"{score_result['multiplicador']*100:.0f}%"],
        ]
        t3 = Table(score_table, colWidths=[6*cm, 11*cm])
        score_color = colors.HexColor(score_result['risco_color'])
        t3.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,0), score_color),
            ('TEXTCOLOR', (0,0), (-1,0), colors.white),
            ('FONTNAME', (0,0), (-1,-1), 'Helvetica-Bold'),
            ('FONTSIZE', (0,0), (-1,-1), 11),
            ('PADDING', (0,0), (-1,-1), 8),
            ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#e2e8f0')),
            ('BACKGROUND', (0,1), (-1,-1), colors.HexColor('#f8fafc')),
        ]))
        story.append(t3)

        # QSA / SOCIOS
        qsa = company_data.get('QSA', company_data.get('qsa', []))
        if qsa:
            story.append(Spacer(1, 0.5*cm))
            story.append(Paragraph("4. QUADRO SOCIETÁRIO (QSA)", h2_style))
            qsa_data = [['Nome', 'CPF/CNPJ', 'Qualificação', 'Entrada', 'Faixa Etária']]
            for s in qsa:
                qsa_data.append([
                    s.get('nome_socio', s.get('nome', 'N/D'))[:30],
                    s.get('cnpj_cpf_socio', s.get('cpf_cnpj', 'N/D')),
                    s.get('qualificacao_socio', s.get('qualificacao', 'N/D'))[:25],
                    s.get('data_entrada_sociedade', 'N/D'),
                    s.get('faixa_etaria', 'N/D'),
                ])
            t4 = Table(qsa_data, colWidths=[4.5*cm, 3.5*cm, 4*cm, 2.5*cm, 2.5*cm])
            t4.setStyle(TableStyle([
                ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#1e40af')),
                ('TEXTCOLOR', (0,0), (-1,0), colors.white),
                ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
                ('FONTSIZE', (0,0), (-1,-1), 8),
                ('PADDING', (0,0), (-1,-1), 5),
                ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#e2e8f0')),
                ('ROWBACKGROUNDS', (0,1), (-1,-1), [colors.white, colors.HexColor('#f1f5f9')]),
            ]))
            story.append(t4)

        # AI ANALYSIS
        story.append(Spacer(1, 0.5*cm))
        story.append(Paragraph("5. ANÁLISE DE INTELIGÊNCIA ARTIFICIAL", h2_style))
        
        # Clean and split AI text
        ai_text = ai_analysis.replace('\n\n', '<br/><br/>').replace('\n', '<br/>')
        story.append(Paragraph(ai_text, body_style))

        # FOOTER
        story.append(Spacer(1, 1*cm))
        story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor('#e2e8f0')))
        story.append(Spacer(1, 0.2*cm))
        story.append(Paragraph(
            f"Relatório gerado automaticamente por CréditoIA | ID #{consulta_id} | {datetime.now().strftime('%d/%m/%Y %H:%M')}",
            small_style))
        story.append(Paragraph(
            "Este relatório é de uso interno e não substitui análise jurídica especializada.",
            ParagraphStyle('Disclaimer', parent=small_style, textColor=colors.HexColor('#9ca3af'))))

        doc.build(story)
        return pdf_path
    except Exception as e:
        print(f"PDF error: {e}")
        import traceback; traceback.print_exc()
        return None

# ─────────────────────────────────────────
# ROUTES
# ─────────────────────────────────────────
@app.route('/')
def dashboard():
    conn = get_db()
    consultas = conn.execute(
        "SELECT * FROM consultas ORDER BY created_at DESC LIMIT 20"
    ).fetchall()
    conn.close()
    return render_template('dashboard.html', consultas=consultas)

@app.route('/nova-consulta')
def nova_consulta():
    cfg = get_api_config()
    return render_template('nova_consulta.html', cfg=cfg)

@app.route('/api/fetch-cnpj', methods=['POST'])
def api_fetch_cnpj():
    data = request.json
    cnpj = clean_cnpj(data.get('cnpj', ''))
    if len(cnpj) != 14:
        return jsonify({'error': 'CNPJ inválido'}), 400
    
    cfg = get_api_config()
    
    # Fetch from all enabled APIs
    opencnpj_data = fetch_opencnpj(cnpj, cfg)
    brasilapi_data = fetch_brasilapi(cnpj, cfg)
    cnpja_data = fetch_cnpja(cnpj, cfg)
    invertexto_data = fetch_invertexto(cnpj, cfg)
    
    merged = merge_company_data(opencnpj_data, brasilapi_data, cnpja_data)
    
    return jsonify({
        'success': True,
        'data': merged,
        'sources': {
            'opencnpj': bool(opencnpj_data and 'cnpj' in opencnpj_data),
            'brasilapi': bool(brasilapi_data and 'cnpj' in brasilapi_data),
            'cnpja': bool(cnpja_data),
            'invertexto': bool(invertexto_data),
        }
    })

@app.route('/api/analisar', methods=['POST'])
def api_analisar():
    data = request.json
    cnpj = clean_cnpj(data.get('cnpj', ''))
    valor_solicitado = float(data.get('valor_solicitado', 0))
    parcelas = int(data.get('parcelas', 12))
    juros = float(data.get('juros', 2.5))
    company_data = data.get('company_data', {})
    
    cfg = get_api_config()
    
    # Judicial data
    nome = company_data.get('razao_social', '')
    judicial_data = fetch_datajud(nome, cfg) if nome else {}
    
    # Social placeholder (scraping would require browser)
    social_data = {
        'instagram': None,
        'linkedin': None,
        'facebook': None,
        'controversias': False,
        'nota': 'Análise de redes sociais requer configuração de scraping adicional.'
    }
    
    # Score
    capital = company_data.get('capital_social', '0')
    score_result = calculate_score(company_data, judicial_data, social_data, valor_solicitado, capital)
    
    # AI Analysis (retorna tupla: texto, ia_usada)
    ai_text, ia_usada = ai_analyze(company_data, judicial_data, social_data, cfg, score_result)
    
    # Save to DB
    from datetime import datetime
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    qsa  = company_data.get('QSA', company_data.get('qsa', []))
    conn = get_db()
    cur = conn.execute("""
        INSERT INTO consultas
        (cnpj, razao_social, nome_fantasia, valor_solicitado, parcelas, juros,
         score_empresa, score_controladores, valor_sugerido, risco,
         situacao_cadastral, porte_empresa, natureza_juridica, capital_social,
         data_inicio_atividade, municipio, uf, email, cnae_principal,
         num_socios, num_processos, dados_json, created_at, updated_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, (
        cnpj,
        company_data.get('razao_social', ''),
        company_data.get('nome_fantasia', ''),
        valor_solicitado, parcelas, juros,
        score_result['score'],
        score_result['score'],
        score_result['valor_sugerido'],
        score_result['risco'],
        company_data.get('situacao_cadastral', ''),
        company_data.get('porte_empresa', company_data.get('porte', '')),
        company_data.get('natureza_juridica', ''),
        str(company_data.get('capital_social', '')),
        company_data.get('data_inicio_atividade', company_data.get('abertura', '')),
        company_data.get('municipio', ''),
        company_data.get('uf', ''),
        company_data.get('email', ''),
        str(company_data.get('cnae_principal', company_data.get('cnae_fiscal', ''))),
        len(qsa),
        0,
        json.dumps({'company': company_data, 'judicial': judicial_data, 'social': social_data, 'ai': ai_text, 'ia_usada': ia_usada}, ensure_ascii=False),
        now, now
    ))
    consulta_id = cur.lastrowid

    # Salvar sócios separadamente
    for s in qsa:
        conn.execute("""
            INSERT INTO socios (consulta_id, nome, cpf_cnpj, qualificacao, data_entrada, faixa_etaria, identificador)
            VALUES (?,?,?,?,?,?,?)
        """, (
            consulta_id,
            s.get('nome_socio', s.get('nome', '')),
            s.get('cnpj_cpf_socio', s.get('cpf_cnpj', '')),
            s.get('qualificacao_socio', s.get('qualificacao', '')),
            s.get('data_entrada_sociedade', ''),
            s.get('faixa_etaria', ''),
            s.get('identificador_socio', s.get('identificador', '')),
        ))
    
    # Generate PDF
    pdf_path = generate_pdf(consulta_id, company_data, score_result, ai_text, valor_solicitado, parcelas, juros)
    if pdf_path and os.path.exists(pdf_path):
        size = os.path.getsize(pdf_path)
        conn.execute("UPDATE consultas SET relatorio_path=?, updated_at=? WHERE id=?",
                     (pdf_path, now, consulta_id))
        conn.execute("""
            INSERT OR REPLACE INTO relatorios (consulta_id, pdf_path, tamanho_bytes, gerado_em)
            VALUES (?,?,?,?)
        """, (consulta_id, pdf_path, size, now))
    
    conn.commit()
    conn.close()
    
    return jsonify({
        'success': True,
        'consulta_id': consulta_id,
        'score': score_result,
        'ai_analysis': ai_text,
        'ia_usada': ia_usada,
        'judicial': judicial_data,
        'social': social_data,
        'has_pdf': bool(pdf_path)
    })

@app.route('/relatorio/<int:consulta_id>')
def ver_relatorio(consulta_id):
    conn = get_db()
    c = conn.execute("SELECT * FROM consultas WHERE id=?", (consulta_id,)).fetchone()
    conn.close()
    if not c:
        return "Relatório não encontrado", 404
    dados = json.loads(c['dados_json'])
    return render_template('relatorio.html', consulta=c, dados=dados)

@app.route('/download-pdf/<int:consulta_id>')
def download_pdf(consulta_id):
    conn = get_db()
    c = conn.execute("SELECT relatorio_path FROM consultas WHERE id=?", (consulta_id,)).fetchone()
    conn.close()
    if c and c['relatorio_path'] and os.path.exists(c['relatorio_path']):
        return send_file(c['relatorio_path'], as_attachment=True,
                         download_name=f"relatorio_credito_{consulta_id}.pdf")
    return "PDF não encontrado", 404

@app.route('/api/config', methods=['GET', 'POST'])
def api_config():
    if request.method == 'POST':
        data = request.json
        from datetime import datetime
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        conn = get_db()
        for key, val in data.items():
            conn.execute(
                "UPDATE api_config SET enabled=?, api_key=?, updated_at=? WHERE key=?",
                (1 if val.get('enabled') else 0, val.get('api_key', ''), now, key)
            )
        conn.commit()
        conn.close()
        return jsonify({'success': True})
    return jsonify(get_api_config())

@app.route('/api/stats')
def api_stats():
    conn = get_db()
    total = conn.execute("SELECT COUNT(*) as c FROM consultas").fetchone()['c']
    baixo = conn.execute("SELECT COUNT(*) as c FROM consultas WHERE risco='BAIXO'").fetchone()['c']
    medio = conn.execute("SELECT COUNT(*) as c FROM consultas WHERE risco='MÉDIO'").fetchone()['c']
    alto = conn.execute("SELECT COUNT(*) as c FROM consultas WHERE risco='ALTO' OR risco='MUITO ALTO'").fetchone()['c']
    avg_score = conn.execute("SELECT AVG(score_empresa) as a FROM consultas").fetchone()['a'] or 0
    conn.close()
    return jsonify({'total': total, 'baixo': baixo, 'medio': medio, 'alto': alto, 'avg_score': round(avg_score, 1)})

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5099))
    debug = os.environ.get('FLASK_ENV') != 'production'
    app.run(debug=debug, host='0.0.0.0', port=port)
