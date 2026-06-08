# MTG Download

Questo workspace contiene uno script minimale per scaricare prodotti `MTG FCI` dal `EUMETSAT Data Store` usando `EUMDAC`.

Script principale: [download_mtg_fci.py](C:/Users/Daniele.LOKI/Documents/medicanes/MTG_data/download_mtg_fci.py)

## Requisiti

- Python 3.9+
- account EUMETSAT con accesso al Data Store
- `consumer key` e `consumer secret` EUMETSAT
- pacchetto Python `eumdac`

Installazione:

```powershell
pip install eumdac
```

## Credenziali

Lo script accetta le credenziali in due modi:

1. da riga di comando
2. tramite variabili d'ambiente

Esempio PowerShell:

```powershell
$env:EUMETSAT_CONSUMER_KEY="la_tua_consumer_key"
$env:EUMETSAT_CONSUMER_SECRET="il_tuo_consumer_secret"
```

In alternativa:

```powershell
python .\download_mtg_fci.py --consumer-key "KEY" --consumer-secret "SECRET" ...
```

Nota: in genere non serve una chiave diversa da quella usata per MSG, se e' gia' una chiave del `EUMETSAT Data Store`. Serve pero' che la licenza del dataset MTG sia attiva sul portale EUMETSAT.

## Uso Base

Lo script cerca i prodotti nell'intervallo temporale richiesto e poi:

- se non specifichi filtri, scarica il prodotto completo
- se specifichi `--coverage`, scarica solo i chunk MTG corrispondenti
- se specifichi `--entry`, scarica solo i file che fanno match con i wildcard indicati

Help:

```powershell
python .\download_mtg_fci.py --help
```

## Parametri Principali

- `--start`: inizio intervallo in UTC, formato `YYYY-MM-DDTHH:MM:SS`
- `--end`: fine intervallo in UTC, formato `YYYY-MM-DDTHH:MM:SS`
- `--collection`: collection EUMETSAT da usare
- `--out`: directory di output
- `--coverage`: area MTG da scaricare (`FD`, `H1`, `H2`, `T1`, `T2`, `T3`, `Q1`, `Q2`, `Q3`, `Q4`)
- `--entry`: wildcard sui singoli file dentro il prodotto
- `--list-only`: elenca i prodotti trovati senza scaricare nulla

Collection di default:

```text
EO:EUM:DAT:0662
```

Questa corrisponde a `MTG FCI L1c normal resolution`.

## Esempi

### 1. Elencare i prodotti senza scaricare

```powershell
python .\download_mtg_fci.py `
  --start 2026-06-03T05:00:00 `
  --end 2026-06-03T06:30:00 `
  --list-only
```

### 2. Scaricare il prodotto completo

```powershell
python .\download_mtg_fci.py `
  --start 2026-06-03T05:00:00 `
  --end 2026-06-03T06:30:00 `
  --out .\downloads_full
```

### 3. Scaricare solo la copertura Europa (`Q4`)

```powershell
python .\download_mtg_fci.py `
  --start 2026-06-03T05:00:00 `
  --end 2026-06-03T06:30:00 `
  --coverage Q4 `
  --out .\mtg_20260603_q4
```

### 4. Scaricare solo file che matchano un wildcard

```powershell
python .\download_mtg_fci.py `
  --start 2026-06-03T05:00:00 `
  --end 2026-06-03T06:30:00 `
  --entry "data/*VIS06*.nc" `
  --out .\downloads_vis06
```

### 5. Usare una collection diversa

```powershell
python .\download_mtg_fci.py `
  --collection EO:EUM:DAT:0665 `
  --start 2026-06-03T05:00:00 `
  --end 2026-06-03T06:30:00 `
  --coverage Q4 `
  --out .\mtg_hr_q4
```

## Nota Sugli Orari

Lo script lavora in `UTC`.

Se il tuo riferimento operativo e' in ora italiana estiva (`CEST`, UTC+2), allora:

- `07:00 CEST` = `05:00 UTC`
- `08:30 CEST` = `06:30 UTC`

Quindi per l'intervallo del `3 giugno 2026` dalle `07:00` alle `08:30` ora italiana, i parametri corretti sono:

```text
--start 2026-06-03T05:00:00
--end   2026-06-03T06:30:00
```

## Struttura Output

Per ogni prodotto trovato, lo script crea una sottocartella dentro `--out`.

Esempio:

```text
mtg_20260603_q4/
  PRODUCT_ID_1/
    data/...
  PRODUCT_ID_2/
    data/...
```

Se scarichi il prodotto completo, dentro la cartella del prodotto troverai l'archivio completo restituito dal Data Store.

## Errori Comuni

### Credenziali mancanti

Messaggio tipico:

```text
Missing credentials. Set --consumer-key/--consumer-secret or the EUMETSAT_CONSUMER_KEY/EUMETSAT_CONSUMER_SECRET environment variables.
```

Soluzione: esportare le variabili d'ambiente o passare le credenziali da CLI.

### Intervallo temporale invertito

Messaggio tipico:

```text
--end must be later than --start.
```

Soluzione: controllare che `--end` sia successivo a `--start`.

### Nessun prodotto trovato

Cause frequenti:

- orario inserito nel fuso sbagliato
- collection non corretta
- licenza del dataset MTG non abilitata

## Estensioni Possibili

Questo script e' volutamente minimale. Le estensioni piu' naturali sono:

- integrazione con lo script MSG gia' esistente
- download batch su piu' intervalli temporali
- retry automatici
- logging su file
- scelta guidata delle collection MTG
