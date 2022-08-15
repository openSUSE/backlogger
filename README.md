# Backlog Status Checker

Produce a document with an overview of your backlog. This can be executed as a script with minimal dependencies or via the provided GitHub Action. The result can be injected into another document such as a README.md or uploaded to a service like GitHub Pages. It is recommended to define a convenient schedule to pull in updates from your issue tracker.

Have a look at the [demo hosted on GitHub Pages](https://kalikiana.github.io/backlogger)!

## Inputs

## config

By default a file *queries.yaml* is expected to contain the queries and limits for your project.

## args

Additional arguments affecting the behavior of the script:

`--reminder-comment-on-issues` can be added here to enable automatic reminder comments. This is **not** enabled by default because it's designed to be used in scheduled runs. Manual execution and previews of changed queries are not expected to have side-effects.

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
      - uses: actions/checkout@v2
      - uses: kalikiana/backlogger@main
          redmine_api_key: ${{ secrets.REDMINE_API_KEY }}
          args: --reminder-comment-on-issues
      - uses: JamesIves/github-pages-deploy-action@v4
        with:
          folder: gh-pages
          clean-exclude: pr-preview
```

## Previews for pull requests

```yaml
concurrency: preview-${{ github.ref }}
on:
  pull_request:
    types:
      - opened
      - reopened
      - synchronize
      - closed
permissions:
  contents: write
  pull-requests: write
jobs:
  backlogger:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v2
      - uses: kalikiana/backlogger@main
        with:
          redmine_api_key: ${{ secrets.REDMINE_API_KEY }}
      - uses: rossjrw/pr-preview-action@v1
```
