{
  schema: "openvoice-v2.model-hashes/v1",
  generated: "2026-08-26",
  models: (
    .models
    | with_entries(.value |= {repository, revision, files})
  )
}
