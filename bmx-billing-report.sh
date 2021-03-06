#!/usr/bin/env bash


celery worker -A bmx-billing-report.celery --loglevel INFO  &
gunicorn  -w 4 -b 0.0.0.0:5000 bmx-billing-report:app --log-level DEBUG
