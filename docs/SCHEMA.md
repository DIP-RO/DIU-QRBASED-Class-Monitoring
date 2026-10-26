# Database schema

```mermaid
erDiagram
  departments ||--o{ users : scopes
  departments ||--o{ teachers : owns
  users ||--o| teachers : maps
  teachers ||--o{ teacher_aliases : has
  rooms ||--o{ room_qr_codes : rotates
  source_configurations ||--o{ sync_runs : records
  source_configurations ||--o{ routine_versions : versions
  routine_versions ||--o{ routine_entries : contains
  teachers ||--o{ routine_entries : assigned
  rooms ||--o{ routine_entries : scheduled
  routine_entries ||--o{ class_sessions : materializes
  policy_versions ||--o{ network_rules : contains
  policy_versions ||--o{ class_sessions : snapshots
  class_sessions ||--o| attendance_records : result
  attendance_records ||--o{ correction_requests : reviewed
  users ||--o{ attendance_attempts : submits
  users ||--o{ audit_events : acts
```

Key database constraints include unique provider subject and email, department-scoped alias tuples, unique room identity, token hashes, routine source keys per version, deterministic session occurrence keys, one attendance record per session/assigned teacher, and one idempotency key per actor. Composite indexes cover teacher/start, department/teaching date, room/start, attendance result, and audit target/time.
