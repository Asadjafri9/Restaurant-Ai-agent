#!/usr/bin/env bash
set -e
case "${SERVICE_MODE:-agent}" in
  admin) exec bash scripts/start_admin.sh ;;
  kfc|kababjees) exec bash scripts/start_tenant.sh ;;
  *) exec bash scripts/start_agent.sh ;;
esac
