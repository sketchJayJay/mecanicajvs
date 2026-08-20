# JVS Mecânica — Sistema de Gestão de Oficina

Sistema web responsivo para a **JVS Mecânica**, preparado para deploy no **Coolify** usando Docker Compose + PostgreSQL persistente.

## Módulos incluídos

- Login administrativo
- Dashboard com indicadores da oficina
- Cadastro e busca de clientes
- Cadastro e edição de veículos com nome/modelo, placa, KM e observações
- **Histórico completo por veículo**
  - Ordens de serviço anteriores
  - Orçamentos do veículo
  - Total já pago
  - Atualização de KM
- Estoque de peças
  - Código, unidade, custo, preço e quantidade
  - Estoque mínimo
  - Alerta de estoque baixo
- Orçamentos
  - Peças e serviços
  - Impressão/PDF
  - Envio pelo WhatsApp
  - Aprovação e conversão em OS
- Ordens de serviço
  - Problema, diagnóstico, peças e serviços
  - Status da execução
  - Baixa automática das peças no estoque ao concluir
  - Bloqueio de conclusão quando não há saldo suficiente
  - Impressão A4
  - **Impressão térmica 80 mm**
  - Envio de resumo pelo WhatsApp
- **Recibos**
  - Recibo A4
  - Recibo térmico 80 mm
  - Liberado quando a OS estiver quitada
- **Contas a receber**
  - Cobrança vinculada à OS
  - Cobranças avulsas
  - Vencimento
  - Pagamento parcial
  - Formas de pagamento
  - Valor pago e saldo em aberto
  - Identificação de cobranças vencidas
  - Cada recebimento é lançado no financeiro automaticamente
- Financeiro
  - Receitas e despesas
  - Entradas geradas por pagamentos de OS/cobranças
  - Total a receber
  - Exclusão de lançamentos com confirmação
  - Exclusão disponível também dentro do relatório mensal
- **Lembretes de manutenção**
  - Troca de óleo
  - Correia dentada
  - Filtros
  - Freios
  - Pneus
  - Revisões
  - Controle por KM e/ou data
  - Avisos de manutenção próxima ou vencida no Dashboard
- **Relatórios mensais**
  - Receitas
  - Despesas
  - Resultado do mês
  - Quantidade de OS
  - Valor total das OS
  - Ranking de serviços/itens
  - Ranking de clientes
  - Gráfico diário de movimentação
  - Exportação CSV
- Dados da empresa
  - Nome
  - Telefone
  - Instagram
  - Endereço
  - Chave PIX
- Exportação de clientes em CSV
- Layout preto + azul seguindo a identidade visual da JVS
- Responsivo para computador, tablet e celular

## Login inicial

Por padrão, se as variáveis não forem alteradas:

- E-mail: `admin@jvs.local`
- Senha: `admin123`

**Troque a senha via `ADMIN_PASSWORD` antes do primeiro deploy.**

## Deploy no Coolify

1. Extraia a pasta/ZIP e envie os arquivos para um repositório Git, ou utilize uma fonte suportada pelo Coolify.
2. No Coolify, crie um recurso do tipo **Docker Compose**.
3. Aponte para o arquivo `docker-compose.yml`.
4. Configure as variáveis de ambiente usando `.env.example` como referência.
5. No serviço `web`, publique a porta interna `8000` e vincule seu domínio.
6. Faça o deploy.
7. A rota `/healthz` pode ser usada para health check.

## Banco de dados e segurança dos dados

O PostgreSQL utiliza o volume Docker persistente:

`jvs_postgres`

Redeploy normal do sistema não apaga o banco. Evite remover o volume do PostgreSQL ao atualizar o sistema.

As novas funções desta versão usam tabelas adicionais e `db.create_all()`, então uma instalação já existente recebe essas novas tabelas automaticamente no primeiro acesso.

## Variáveis principais

Veja `.env.example`.

- `SECRET_KEY`
- `POSTGRES_DB`
- `POSTGRES_USER`
- `POSTGRES_PASSWORD`
- `DATABASE_URL`
- `ADMIN_EMAIL`
- `ADMIN_PASSWORD`

## Teste local

```bash
python -m venv .venv
# Windows
.venv\\Scripts\\activate
# Linux/macOS
source .venv/bin/activate

pip install -r requirements.txt
python app.py
```

Abra `http://127.0.0.1:5000`.

Com Docker Compose:

```bash
docker compose up --build
```

## Atualização desta versão

Esta é a versão ampliada da JVS Mecânica com histórico do veículo, recibos, impressão térmica, WhatsApp, contas a receber, lembretes de óleo/correia e relatórios mensais.


## Atualização v2.5
- Busca de OS por número, cliente, telefone, placa, marca/modelo, problema ou diagnóstico.
- Filtro por status da OS.
- Listagem de OS salvas reorganizada e corrigida para celular.
- Botões Abrir, Editar e Excluir em cada OS.
- Tela para editar cliente, veículo, problema, diagnóstico e observações da OS.
- Exclusão de OS preservando lançamentos financeiros já existentes.
- Nenhuma alteração de estrutura do banco de dados é necessária nesta atualização.


## Atualização v2.6
- Botão Excluir em cada orçamento salvo.
- Opção Excluir orçamento também dentro da tela de detalhes.
- Confirmação antes da exclusão para evitar apagamentos acidentais.
- Ao excluir um orçamento aprovado, a OS já criada é preservada.
- Itens do orçamento são excluídos junto com o orçamento.
- Nenhuma alteração de estrutura do banco de dados é necessária nesta atualização.
