# GrainStorm backend documentation

GrainStorm is maintained as a Python API and CLI project. Frontend development
is discontinued; any client can consume the documented JSON endpoints.

## API and operations

- [Project setup and structure](../README.md)
- [Rotation-advice workflow](rotation_advice.md): primary agricultural analysis request and response states.
- [API contract](api_contract.md): individual endpoints, inputs, units, errors and provenance.
- [TypeScript client types](api-types.ts): optional integration aid; no browser runtime required.
- [Intelligence API](intelligence.md): Gemini setup, report schema, consistency validation, caching and quotas.
- [Satellite context and worker](satellite_context.md): Earthdata credentials, bounded acquisition, polling and cache ingestion.
- [Backend roadmap](TODO.md): completed work, remaining implementation and validation.

## Data and research

- [Crop profiles](crop_profiles_v1.md)
- [Soil moisture sources](soil_moisture.md) and [sample analysis](soil_moisture_analysis.md)
- [Rainfall source compatibility](rainfall_source_compatibility.md)
- [Farming practices research plan](farming_practices_task_schedule.md)
- [Challenge resource triage](challenge_resources_triage.md)

Research notes describe their original datasets and experimental context. They
are evidence records, not guarantees of current geographic coverage or accuracy.
