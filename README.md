# Backlog Status Checker

Produce a document with an overview of your backlog. This can be executed as a script with minimal dependencies or via the provided GitHub Action. The result can be injected into another document such as a README.md or uploaded to a service like GitHub Pages. It is recommended to define a convenient schedule to pull in updates from your issue tracker.

Have a look at the [demo hosted on GitHub Pages](https://openSUSE.github.io/backlogger)!

## Inputs

## config

By default a file *queries.yaml* is expected to contain the queries and limits for your project.

## args

Additional arguments affecting the behavior of the script:

`--reminder-comment-on-issues` can be added here to enable automatic reminder comments. This is **not** enabled by default because it's designed to be used in scheduled runs. Manual execution and previews of changed queries are not expected to have side-effects.

`--exit-code` can be added to also emit return code 3 if any of the configured queries is not within its limit.

## folder

The output folder for the generated HTML. By default this is `gh-pages`.

## redmine_api_key

For the action to be able to access the Redmine API you need to configure `REDMINE_API_KEY` via **Settings** > **Secrets**. In Redmine itself you can create or lookup the key under **My Account** > **API Access key**.

## Continuous updates

```yaml
on:
  schedule:
  - cron: '*/10 * * * *'
permissions:
  contents: write
jobs:
  backlogger:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v6
      - uses: openSUSE/backlogger@main
        with:
          redmine_api_key: ${{ secrets.REDMINE_API_KEY }}
          args: --reminder-comment-on-issues
      - uses: JamesIves/github-pages-deploy-action@v4
        with:
          folder: gh-pages
          clean-exclude: pr-preview
```

## Previews for pull requests

To securely generate and deploy previews for pull requests (including those from forks), use a secure two-workflow "Build and Deploy" pattern.

### 1. Build Workflow

Create `.github/workflows/preview-build.yml` triggered on the `pull_request` event:

```yaml
name: Preview Build
concurrency: preview-${{ github.ref }}
on:
  pull_request:
    types: [opened, reopened, synchronize, closed]
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Run backlogger
        if: github.event.action != 'closed'
        uses: openSUSE/backlogger@main
        with:
          redmine_api_key: ${{ secrets.REDMINE_API_KEY }}
      - name: Save PR info
        run: |
          mkdir -p pr-info
          echo "${{ github.event.number }}" > pr-info/pr-number
          echo "${{ github.event.action }}" > pr-info/pr-action
      - uses: actions/upload-artifact@v4
        with:
          name: pr-info
          path: pr-info/
      - name: Upload preview artifact
        if: github.event.action != 'closed'
        uses: actions/upload-artifact@v4
        with:
          name: preview-artifact
          path: gh-pages/
```

### 2. Deploy Workflow

Create `.github/workflows/preview-deploy.yml` triggered on the `workflow_run` event:

```yaml
name: Preview Deploy
on:
  workflow_run:
    workflows: ["Preview Build"]
    types: [completed]
jobs:
  deploy:
    runs-on: ubuntu-latest
    if: github.event.workflow_run.event == 'pull_request' && github.event.workflow_run.conclusion == 'success'
    steps:
      - uses: actions/checkout@v4
      - name: Download PR info
        uses: actions/download-artifact@v4
        with:
          run-id: ${{ github.event.workflow_run.id }}
          name: pr-info
          path: pr-info
      - id: pr-info
        run: |
          echo "number=$(cat pr-info/pr-number)" >> "$GITHUB_OUTPUT"
          echo "action=$(cat pr-info/pr-action)" >> "$GITHUB_OUTPUT"
      - name: Download preview
        if: steps.pr-info.outputs.action != 'closed'
        uses: actions/download-artifact@v4
        with:
          run-id: ${{ github.event.workflow_run.id }}
          name: preview-artifact
          path: gh-pages
      - uses: rossjrw/pr-preview-action@v1
        id: preview-step
        with:
          source-dir: gh-pages
          action: ${{ steps.pr-info.outputs.action == 'closed' && 'remove' || 'deploy' }}
          pr-number: ${{ steps.pr-info.outputs.number }}
          comment: false
      - name: Comment on PR (deploy)
        if: steps.pr-info.outputs.action != 'closed'
        uses: marocchino/sticky-pull-request-comment@v2
        with:
          header: pr-preview
          number: ${{ steps.pr-info.outputs.number }}
          message: |
            View preview at: ${{ steps.preview-step.outputs.preview-url }}
      - name: Comment on PR (remove)
        if: steps.pr-info.outputs.action == 'closed'
        uses: marocchino/sticky-pull-request-comment@v2
        with:
          header: pr-preview
          number: ${{ steps.pr-info.outputs.number }}
          message: Preview removed because the pull request was closed.
```

## License

This project is licensed under the MIT license, see LICENSE file for details.
