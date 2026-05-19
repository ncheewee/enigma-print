# Google Drive Backend Plan

Google Drive can be the backend for this MVP. The simplest version is to treat Drive as a folder of project manifests and generated print files, not as a relational database.

## Folder Layout

```text
EnigmaPrint/
  projects/
    week-20-clockwork-garden/
      manifest.json
      source-hidden.png
      day-01.stl
      day-01.3mf
      day-02.stl
      day-02.3mf
```

## App Model

The dashboard only needs three Drive operations:

1. List folders inside `EnigmaPrint/projects`.
2. Read each folder's `manifest.json`.
3. Update `manifest.json` when a piece is marked printed.

Generated assets can stay as normal Drive files and be linked from the manifest.

## Recommended MVP Integration

Start with manual export/import:

- The dashboard exports a project manifest JSON.
- A generator script writes that manifest and files into a local project folder.
- The folder can be synced to Google Drive with the desktop Drive app.

Then add direct Drive API sync:

- Browser OAuth with Google Identity Services.
- Drive API file listing for the project folder.
- Drive API upload/update for `manifest.json`.
- Optional Drive Picker for choosing the root `EnigmaPrint` folder.

This keeps the first build small while preserving a clean path to cloud sync.
