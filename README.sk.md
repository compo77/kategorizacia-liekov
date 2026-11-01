# Porovnanie liekov ATC B01AB05

[English](README.md) | **Slovenčina**

Jednoduchá webová aplikácia bez databázy. Z archívu Ministerstva zdravotníctva SR vyhľadá dva najnovšie zoznamy kategorizovaných liekov, načíta ich excelové súbory a porovná cenu a doplatok liekov v zvolenej ATC skupine. Dostupné skupiny a predvolenú voľbu definuje `config/atc_groups.yaml`; pridaním skupiny do tohto súboru sa automaticky zobrazí vo výbere. Údaje sa ukladajú iba do pamäte procesu na štyri hodiny; pri dočasnom výpadku zdroja sa v bežiacom procese ponechá posledné úspešné načítanie.

Napríklad priamy odkaz na nadroparín je `/?atc=B01AB06`.

Ďalšiu skupinu pridajte pod `groups` v `config/atc_groups.yaml`:

```yaml
groups:
  B01AB99:
    name: Názov liečiva
```

V existujúcom súbore ponechajte ostatné skupiny a nastavte `default` na niektorý z nakonfigurovaných kódov. Po úprave YAML reštartujte lokálnu aplikáciu; pri Cloud Run vytvorte a nasaďte nový image.

## Štruktúra projektu

```text
.
├── .dockerignore
├── .github/
│   └── agents/
│       └── lieky-local-runner.agent.md
├── .gitignore
├── .pre-commit-config.yaml
├── Dockerfile
├── Makefile
├── README.md
├── README.sk.md
├── app.py
├── config/
│   └── atc_groups.yaml
├── medicine_comparison/
│   ├── __init__.py
│   ├── config.py
│   ├── service.py
│   └── source.py
├── pyproject.toml
├── requirements.txt
├── static/
│   ├── app.js
│   └── style.css
├── templates/
│   └── index.html
└── tests/
    └── test_comparison.py
```

- `app.py` vytvára Flask aplikáciu, spracúva webové požiadavky a formátuje zobrazené ceny.
- `config/atc_groups.yaml` definuje dostupné ATC skupiny a predvolený výber; `medicine_comparison/config.py` konfiguráciu načíta a overí.
- `medicine_comparison/source.py` vyhľadáva zoznamy MZ SR, sťahuje excelové súbory a načítava údaje o liekoch.
- `medicine_comparison/service.py` páruje lieky medzi zoznamami, počíta zmeny cien a doplatkov a ukladá výsledky do vyrovnávacej pamäte na štyri hodiny.
- `templates/index.html`, `static/app.js` a `static/style.css` tvoria stránku s porovnaním, vyhľadávanie v tabuľke a jej štýly.
- `tests/test_comparison.py` testuje konfiguráciu, načítanie tabuliek, porovnanie, vykreslenie stránky a health endpoint.
- `pyproject.toml` definuje základné runtime závislosti a lokálnu vývojovú skupinu nástrojov na linting, typovú kontrolu, formátovanie a testy.
- `.pre-commit-config.yaml` spúšťa lokálne overenia kódu pred commitom a pushom.
- `Dockerfile` zostavuje a spúšťa aplikáciu v Cloud Run; `requirements.txt` je vygenerovaný minimálny súbor runtime závislostí pre nasadenie.

## Lokálne spustenie cez uv

Vyžaduje sa Python 3.13+ a [uv](https://docs.astral.sh/uv/).

```sh
make dev
```

Tým sa nainštalujú runtime závislosti aj lokálne nástroje pre vývoj, ako `ruff`, `black`, `mypy` a `pytest`, bez zaťaženia produkčného kontajnera.

Spustenie aplikácie:

```sh
make run
```

Aplikácia bude dostupná na `http://localhost:8080`. Prvé načítanie stiahne tabuľky z webu ministerstva.

## Lokálne zostavenie a spustenie produkčného Docker image

Vyžaduje sa Docker. Na macOS s Colima najskôr spustite Docker daemon:

```sh
colima start
```

Zostavenie a spustenie produkčného image:

```sh
make docker-build
make docker-run
```

Kontajner počúva iba na `127.0.0.1:8082`; v druhom termináli ho overte príkazom:

```sh
make docker-check
```

`docker-run` beží v popredí a po zastavení kontajner odstráni. Tag image alebo port možno zmeniť, napríklad `make docker-build IMAGE=my-app:local` alebo `make docker-run DOCKER_PORT=8083`.

## Kontrola kvality kódu

```sh
make lint
make typecheck
make test
.venv-dev/bin/ruff format --check .
.venv-dev/bin/black --check .
```

Voliteľne:

```sh
.venv-dev/bin/pre-commit install
```

## Minimálne závislosti pre nasadenie

Projekt udržuje minimálny runtime súbor pre produkčné nasadenie. Vygeneruje sa pomocou:

```sh
uv export --no-dev --format requirements-txt > requirements.txt
```

Tento súbor je určený pre Cloud Run alebo iné produkčné nasadenie. Neobsahuje lokálne vývojové nástroje, ktoré zostávajú v skupine `dev` v `pyproject.toml`.

## Google Cloud Run

Vytvorte Docker repository v Artifact Registry a nastavte premenné:

```sh
gcloud artifacts repositories create lieky \
  --repository-format=docker --location=REGION
make cloud-build CLOUD_REGION=REGION CLOUD_PROJECT=PROJECT_ID
make cloud-deploy CLOUD_REGION=REGION CLOUD_PROJECT=PROJECT_ID
make cloud-check CLOUD_REGION=REGION
```

Artifact Registry repository vytvorte iba raz. Prihláste sa cez `gcloud auth login` a nastavte aktívny projekt príkazom `gcloud config set project PROJECT_ID`; Docker musí mať nakonfigurované prihlasovanie do Artifact Registry. Make ciele štandardne použijú aktívny projekt, región `europe-west1`, repository `lieky`, image `kategorizacia-liekov:latest` a existujúcu Cloud Run službu `b01ab05`; hodnoty možno podľa potreby prepísať. `make cloud-build` lokálne cez Docker Buildx zostaví image `linux/amd64` kompatibilný s Cloud Run a odošle ho do Artifact Registry; účet potrebuje oprávnenie zapisovať do Artifact Registry. Názov služby zostáva `b01ab05`, aby sa aktualizovala existujúca služba; image v Artifact Registry používa názov projektu. Účet na nasadenie potrebuje oprávnenie spravovať Cloud Run služby. Kontajner počúva na porte `PORT`, ktorý Cloud Run nastavuje automaticky; `make cloud-check` overí endpoint `/status`. Pri pridaní skupiny do YAML image netreba meniť Python kód; novú konfiguráciu stačí zahrnúť do nového image.

## Poznámka k údajom

V tabuľke sú cena konečná, úradne určená cena (ÚZP) a doplatok pacienta (DOP) z excelového zoznamu MZ SR. Zobrazený doplatok je hodnota uvedená v súbore za celé balenie. Najnovší zoznam môže byť označený ako informatívny materiál; obdobia a originálne súbory sú dostupné priamo v hlavičke aplikácie.
