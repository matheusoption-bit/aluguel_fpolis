# Monitor imobiliario na nuvem (piloto)

**Objetivo:** buscar anuncios de locacao residencial de imobiliarias na Grande Florianopolis diariamente, sem depender de computador ligado.

## Situacao e abrangencia

- Registro de **50 marcas**, incluindo **45 com oferta residencial identificada ou declarada**, das quais **39 possuem site inicial utilizavel** e **6 exigem encontrar site proprio**; 5 ficam fora ate confirmar aluguel residencial.
- **Piloto diario:** 5 fontes (Ibagy, San Remo, Kabral, Adriano e Imobiliaria Biguacu). A listagem no cadastro **nao comprova coletor funcionando** nem cobertura integral dos anuncios.
- Busca paginas publicas somente se a regra robots.txt estiver acessivel e permitir; nao contorna captchas, login ou proibicoes.
- Varredura parcial, com limite de 8 links de anuncios por fonte no piloto; sites dinamicos ou sem seletor compativel ficarao marcados para revisao.
- Nao calcula rotas e nao verifica todos os campos de criterios pessoais. Valores ausentes permanecem vazios. Um bloqueio nao significa "zero imoveis".
- A primeira execucao apenas valida alcance e extracao; a expansao depende de adaptadores e comprovacao por site.

## Agendamento

Workflow: `.github/workflows/monitor-imoveis.yml`

- Todos os dias as **08h17 de Brasilia** (11h17 UTC); o GitHub pode atrasar ou, excepcionalmente, omitir agendamentos.
- O cron **so entra em operacao depois de o workflow estar na branch principal `main`**.
- Permissao de leitura no GitHub; nao altera outros repositorios nem faz commits de anuncios.
- Dados incrementais em cache de execucoes do GitHub (sujeito a expiracao/eviccao).
- Relatorios diarios para baixar na aba **Actions > Monitor imobiliario - piloto diario > execucao > Artifacts**, por 14 dias.
- O GitHub nao envia e-mails de imoveis automaticamente neste piloto.

## Saidas

- `out/catalogo.csv`: anuncios historicos encontrados nessa integracao;
- `out/novos.csv`: anuncios com URLs novas na rodada;
- `out/status_fontes.csv`: resultados por imobiliaria, inclusive erros e pendencias;
- `out/resumo.json`: horario, total, fontes testadas e estado da sincronizacao.

A coleta nao apaga registros antigos por falta de acesso a um site. Deduplicacao inicial por URL canonica; imoveis repetidos em imobiliarias diferentes ainda podem requerer conciliacao.

## Integracao com planilha Santa Luzia

A planilha existe em: https://docs.google.com/spreadsheets/d/1NliaU6OX_hE-Yq4K9DHteLnGnND30dAFGWV2xx8m6P8/edit

Para gravar automaticamente nela:
1. Em um projeto Google Cloud sob controle do usuario, ativar a **Google Sheets API** e criar uma *service account* de minimo privilegio; gerar credencial JSON de acesso para essa conta e compartilhe **somente essa planilha** com o e-mail da conta de servico como Editora.
2. Converter o arquivo JSON de credencial em Base64 **na propria maquina**, sem colar o JSON ou Base64 em um chat, documento publico, issue ou codigo.
3. Em GitHub > Settings > Secrets and variables > Actions > Repository secrets, criar os segredos:
   - `GOOGLE_SERVICE_ACCOUNT_JSON_B64`: Base64 do JSON;
   - `GOOGLE_SHEET_ID`: ID da planilha (segmento entre `/d/` e `/edit` no link).
4. Testar manualmente o workflow e conferir a aba `Anúncios`. O motor apenas acrescenta linhas novas cujo ID nao existe na coluna S e nao substitui o historico anterior.

**Importante:** a conexao do Google Drive ao ChatGPT NAO equivale a uma credencial reutilizavel pelo GitHub Actions. Sem os segredos, o workflow roda e gera os arquivos, mas a planilha retorna `AGUARDANDO_CREDENCIAL`.

## Seguranca e custos

O repositorio atual e publico: dados incluidos em fontes, logs e artefatos podem ser visiveis. **Nao inclua enderecos pessoais, senha ou outros dados privados no repositorio.** Mantenha criterios pessoais somente na planilha com acesso controlado ou em configuracoes privadas.

Usa runners hospedados no GitHub e plano gratuito inicialmente. Podera haver cobranca apenas se as regras do plano/repositorio ou servicos adicionais mudarem; conferir consumo na aba Billing. Nenhuma assinatura paga foi ativada.

## Testes

Em qualquer ambiente Python 3.12:

```bash
python -m pip install -r monitor_nuvem/requirements.txt
python -m unittest discover -s monitor_nuvem/tests -v
python monitor_nuvem/monitor.py --limit 1 --max-details 2
```

Para pausa: GitHub > Actions > Monitor imobiliario - piloto diario > Disable workflow, ou retire o horario do arquivo. Revisar a qualidade das fontes e das duplicatas antes de aumentar o limite de cinco para todas as fontes.

**Estado:** o teste offline nao equivale a coleta real. O resultado da verificacao online do GitHub Actions deve ser consultado antes de declarar qualquer imobiliaria integrada.
