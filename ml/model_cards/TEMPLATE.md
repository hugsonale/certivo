# Model card: {{name}}

> {{banner}}

## Model details

- **Name and version:** {{name}}
- **Kind:** {{kind}}
- **Input and output:** {{io}}
- **How it was trained:** {{training}}
- **Code and settings:** this repository's `ml/` folder; every setting is in `ml/params.yaml`.

## Intended use

{{intended_use}}

## Not for

{{out_of_scope}}

## Training data

- **Dataset:** {{dataset}} (data sheet: `{{datasheet}}`)
- **Fingerprint:** `{{data_sha256}}`
- **Origin and permission:** {{data_origin}}
- **Split:** {{split}}

## Evaluation

Measured once on the held-out test split. Each rate comes with a 95 percent interval (Wilson), because a count is only an estimate.

{{evaluation_table}}

By group (the groups are made up in this baseline):

{{group_table}}

## Limits and risks

{{limits}}

## Fairness and robustness

{{fairness}}

## Promotion status

{{promotion}}

## Reproduce

{{reproduce}}

## Licence and provenance

{{licence}}
