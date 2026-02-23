# 🚀 Deploy no Render — Passo a Passo Completo

## O que você vai precisar
- Conta no **GitHub** (gratuito) → https://github.com
- Conta no **Render** (gratuito) → https://render.com
- Suas chaves de API (Anthropic e/ou Perplexity)

---

## PASSO 1 — Subir o projeto no GitHub

### Opção A: Pelo navegador (sem instalar nada)

1. Acesse https://github.com e faça login
2. Clique em **"New"** (botão verde)
3. Nome do repositório: `creditoia`
4. Deixe como **Public** ou **Private** (tanto faz)
5. Clique em **"Create repository"**
6. Na próxima tela, clique em **"uploading an existing file"**
7. Arraste **TODOS** os arquivos e pastas do `credito_app`:
   ```
   app.py
   requirements.txt
   Procfile
   render.yaml
   railway.toml
   templates/  (pasta inteira)
   db/         (pasta vazia, só para criar)
   ```
8. Clique em **"Commit changes"**

### Opção B: Pelo terminal (Git instalado)
```bash
cd C:\Users\annib\Desktop\credito_app
git init
git add .
git commit -m "primeiro commit"
git branch -M main
git remote add origin https://github.com/SEU_USUARIO/creditoia.git
git push -u origin main
```

---

## PASSO 2 — Criar o Web Service no Render

1. Acesse https://render.com e faça login (pode usar GitHub)

2. Clique em **"New +"** → **"Web Service"**

3. Clique em **"Connect a repository"**

4. Autorize o Render a acessar seu GitHub

5. Selecione o repositório **creditoia**

6. Configure o serviço:

   | Campo | Valor |
   |---|---|
   | **Name** | creditoia |
   | **Region** | Oregon (US West) ou São Paulo |
   | **Branch** | main |
   | **Runtime** | Python 3 |
   | **Build Command** | `pip install -r requirements.txt` |
   | **Start Command** | `gunicorn app:app --bind 0.0.0.0:$PORT --workers 2 --timeout 120` |
   | **Instance Type** | **Free** |

7. Clique em **"Advanced"** e adicione as variáveis de ambiente:

   | Key | Value |
   |---|---|
   | `FLASK_ENV` | `production` |
   | `RENDER` | `true` |
   | `ANTHROPIC_API_KEY` | `sk-ant-...` (sua chave) |
   | `PERPLEXITY_API_KEY` | `pplx-...` (sua chave) |

8. Clique em **"Create Web Service"**

---

## PASSO 3 — Adicionar disco persistente (IMPORTANTE!)

> Sem o disco, o banco de dados é apagado toda vez que o serviço reinicia.

1. No painel do seu serviço no Render, clique em **"Disks"** no menu lateral
2. Clique em **"Add Disk"**
3. Configure:
   | Campo | Valor |
   |---|---|
   | **Name** | credito-data |
   | **Mount Path** | `/data` |
   | **Size** | 1 GB |
4. Clique em **"Save"**

> ⚠️ O disco de 1GB custa **$0,25/mês** no Render. O serviço web em si é gratuito.
> Se não quiser pagar nada, pode pular o disco — mas os dados são perdidos ao reiniciar.

---

## PASSO 4 — Aguardar o deploy

- O Render vai instalar todas as dependências automaticamente
- Acompanhe os logs em tempo real na aba **"Logs"**
- O processo leva de **3 a 6 minutos** na primeira vez
- Quando aparecer `Listening on http://0.0.0.0:XXXX` nos logs, está pronto!

---

## PASSO 5 — Acessar o sistema

Sua URL vai ser algo como:
```
https://creditoia.onrender.com
```

Clique no link que aparece no topo do painel do Render.

---

## ⚠️ Limitações do plano gratuito do Render

| Limitação | Detalhe |
|---|---|
| **Dorme após 15min** | O serviço "dorme" se ninguém acessar. O primeiro acesso demora ~30 segundos para "acordar" |
| **750h/mês** | Suficiente para uso contínuo de 1 serviço |
| **Sem disco grátis** | O banco SQLite fica na pasta temporária (perdido ao reiniciar) |

### Como evitar o "sleep" (opcional)
Use o **UptimeRobot** (gratuito) para fazer ping a cada 5 minutos:
1. Acesse https://uptimerobot.com
2. Cadastre um monitor HTTP para sua URL do Render
3. Intervalo: 5 minutos
4. Pronto — o serviço nunca dorme!

---

## Atualizar o sistema após mudanças

Sempre que modificar o código:

**Pelo GitHub (navegador):**
1. Edite o arquivo direto no GitHub
2. Commit → O Render faz o redeploy automaticamente

**Pelo terminal:**
```bash
git add .
git commit -m "descrição da mudança"
git push
```
O Render detecta o push e faz o deploy automático em ~2 minutos.

---

## Onde pegar as chaves de API

| API | Link | Observação |
|---|---|---|
| **Anthropic** | https://console.anthropic.com/settings/keys | Requer cadastro e cartão |
| **Perplexity** | https://www.perplexity.ai/settings/api | Requer saldo mínimo $5 |

---

## Problemas comuns

**"Module not found"**
→ Verifique se o `requirements.txt` está na raiz do repositório

**"No such file: templates/dashboard.html"**
→ Certifique que a pasta `templates/` foi enviada ao GitHub com os 3 arquivos HTML

**Banco de dados zerado após reiniciar**
→ Configure o Disco Persistente no passo 3

**Timeout na análise**
→ Normal para plano free. O `--timeout 120` no Start Command já foi configurado para evitar isso.
