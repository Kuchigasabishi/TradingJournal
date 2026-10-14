# Vendored Swagger UI

swagger-ui-dist 5.33.2 (Apache-2.0). The four files here are copied unmodified from the npm tarball:
`swagger-ui-bundle.js`, `swagger-ui.css`, `LICENSE` and `NOTICE`.

- Source: https://www.npmjs.com/package/swagger-ui-dist
- Integrity: the tarball's SHA-512 matched the registry's published `dist.integrity`
  (`sha512-MyrWX06zkJRYPnIau8Qj8F6KfzS+Qj8D9AR36vCWkkC9ts1r1DYF84apgCvZBzO2Wzm7G7loCd5VS+4JLWoyLQ==`) before extraction.
- Served at `/api/docs-assets` by `app/api/docs.py`, so `/api/docs` works offline and verification never leaves the machine.

To update: `npm pack swagger-ui-dist@<version>`, compare the tarball's SHA-512 with
`npm view swagger-ui-dist@<version> dist.integrity`, copy the same four files, and edit this note.
