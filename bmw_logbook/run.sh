#!/usr/bin/with-contenv bashio
# shellcheck shell=bash
bashio::log.info "Käynnistetään BMW-ajopäiväkirja..."
cd /app || exit 1
exec python3 -m logbook.main
