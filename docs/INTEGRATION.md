# Timetable and identity integration

Google OIDC and Firestore routine authorization are separate. A verified institutional email can authenticate a mapped local user but does not automatically authorize Firestore reads or grant an administrator role.

Register an OIDC web client with callback `${PUBLIC_BASE_URL}/auth/callback`. Configure client ID/secret and allowed domains. The server library validates issuer, signature, audience, expiry, state, nonce and verified-email claims; PKCE is enabled. Map the stable provider subject plus verified email to an active local user.

For routine sync, provision an approved read-only integration identity for project `diu-campus-schedule-cc857`. Supply renewable credential material using the institution's secret system; never put tokens in SQLite, browser code or QR data. The included adapter accepts an environment-provided bearer token and pages the `routines` collection. Because current live permission and schema have not been verified with an authorized credential, deployments must display live sync as unconnected until a complete read, normalization and atomic version commit succeed.

Supported import aliases include `data.schedule` and top-level `schedule`, `teacherInitial` / `teacher_initial`, and `courseCode` / `course_code`. Failed or partial fetches do not replace the last good version.

