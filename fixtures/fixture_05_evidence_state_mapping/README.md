# fixture_05_evidence_state_mapping

- Root: `urn:uuid:00000005-0000-4000-8000-000000000005` (`evidence`)
- Closure: `closed`
- Source: synthetic deterministic evidence records from the orthogonal
  evidence contract.
- Minimal closure: request, candidates snapshot, and evidence.
- Clean coverage: entity and relation subjects, official-report and
  API-estimate derivations, distinct source discriminators, freshness,
  normalization, and display fields.
- Dirty case: replace an official source discriminator with `model` and expect
  the exact Schema rejection. A model is permitted as a derivation mechanism,
  never as a fact source type.
- Non-coverage: deterministic external five-state mapping and evidence truth;
  these remain for WU3.
