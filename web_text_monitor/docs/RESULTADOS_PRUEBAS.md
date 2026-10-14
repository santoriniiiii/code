# Resultados reales de las pruebas

Este documento corresponde al entregable **F**. Todo lo que aparece aquí se ha ejecutado de verdad.

## Entorno donde se ejecutaron

| | |
|---|---|
| Sistema | Linux x86_64 (contenedor), **no macOS** |
| Python | 3.13.16 (salida completa abajo) y 3.11.15 (mismo resultado: `121 passed`) |
| Dependencias | Las de `requirements-dev.txt`: playwright 1.56.0, requests 2.34.2, beautifulsoup4 4.15.0, pytest 9.1.1 |
| Navegador | Chromium 141.0.7390.37 (versión 1194 de Playwright) |
| Red | Solo 127.0.0.1 y archivos locales; ninguna prueba accede a internet |

La suite completa se ejecutó tres veces seguidas con Python 3.13 (`121 passed` cada vez) para descartar
pruebas inestables por temporización. Con `-m "not browser"` se ejecutan 108 pruebas sin abrir el navegador.

**Qué no cubren:** la ejecución en macOS/Apple Silicon, tu página real (aún no definida) y el comando
`login` con ventana visible (el contenedor no tiene pantalla). Para eso está la
[lista de validación del README](../README.md#lista-de-validación).

## Casos pedidos y prueba que los cubre

| # | Caso | Pruebas |
|---|---|---|
| 1 | Texto presente desde la primera observación | `test_state_machine.py::test_text_present_from_first_observation_only_sets_baseline`, `test_baseline_with_confirmation_needs_n_equal_observations` |
| 2 | Aparición de un texto | `test_state_machine.py::test_text_appears` |
| 3 | Desaparición de un texto | `test_state_machine.py::test_text_disappears` |
| 4 | Sustitución de un texto por otro | `test_state_machine.py::test_text_replaced_by_another`, `test_replacement_by_unconfigured_text_keeps_excerpt` |
| 5 | Ausencia de cambios | `test_state_machine.py::test_no_change_produces_no_events` |
| 6 | Dos observaciones consecutivas del mismo estado | `test_state_machine.py::test_change_confirmed_after_two_consecutive_observations`, `test_single_flicker_is_filtered`, `test_alternating_candidates_restart_the_count` |
| 7 | Lectura desconocida | `test_state_machine.py::test_unknown_reading_keeps_state_and_is_recorded_once`, `test_unknown_policy_*`; `test_text_detector.py::test_element_missing_is_unknown_by_default` |
| 8 | Error de conexión | `test_state_machine.py::test_connection_error_is_not_a_disappearance`; `test_integration_http.py::test_connection_refused_is_error`; `test_integration_browser.py::test_server_down_and_back` |
| 9 | Error de escritura del CSV | `test_event_logger.py::test_write_error_keeps_rows_pending_and_retries`, `test_unsaved_rows_are_returned_on_close`, `test_parent_path_is_a_file_gives_clear_error`; `test_monitor.py::test_csv_write_failure_is_retried_on_next_cycle` |
| 10 | Reinicio del programa | `test_state_machine.py::test_restart_*`; `test_monitor.py::test_restart_resumes_without_duplicating_events`, `test_resume_disabled_sets_new_baseline`; `test_event_logger.py::test_restart_appends_and_keeps_history` |
| 11 | Recuperación después de una interrupción | `test_state_machine.py::test_recovery_keeps_baseline_and_reports_change_window`, `test_recovery_with_rebaseline_policy_records_new_baseline_not_a_change`; `test_integration_browser.py::test_http_503_is_error_and_reading_recovers`, `test_browser_crash_is_recovered_by_relaunching` |
| 12 | Prevención de eventos duplicados | `test_state_machine.py::test_no_duplicate_events_over_long_sequence`, `test_event_ids_are_unique`; `test_event_logger.py::test_second_monitor_on_same_csv_is_rejected` |
| 13 | Mayúsculas y minúsculas | `test_text_detector.py::test_insensitive_by_default_and_keeps_page_spelling`, `test_case_sensitive_global`, `test_case_sensitive_per_target_overrides_global` |
| 14 | Varios textos presentes al mismo tiempo | `test_text_detector.py::test_multiple_states_*`, `test_synonyms_map_to_same_state_without_conflict`; `test_state_machine.py::test_independent_texts_with_combined_policy`, `test_conflicting_texts_never_confirm_a_change` |
| 15 | Cambio de zona horaria | `test_event_logger.py::test_local_time_follows_configured_timezone[...]` (Lima, Madrid en invierno y verano, UTC), `test_local_date_changes_at_local_midnight`; `test_config.py::test_invalid_timezone` |
| 16 | Cierre ordenado con Ctrl+C | `test_monitor.py::test_ctrl_c_during_observation_finishes_it_and_closes_cleanly`, `test_error_caused_by_shutdown_is_not_recorded`, `test_keyboard_interrupt_still_writes_stop_marker`; `test_integration_http.py::test_full_program_http_mode_stops_cleanly_on_sigint` y `test_integration_browser.py::test_full_program_browser_mode_stops_cleanly_on_sigint` (programa real en un subproceso, SIGINT al grupo de procesos como hace la terminal) |

## Ejecución completa más reciente (`python -m pytest -v`, Python 3.13.16)

```
============================= test session starts ==============================
platform linux -- Python 3.13.16, pytest-9.1.1, pluggy-1.6.0 -- .venv/bin/python
rootdir: web_text_monitor
configfile: pytest.ini
testpaths: tests
collecting ... collected 121 items

tests/test_config.py::test_shipped_configs_are_valid[config.example.toml] PASSED [  0%]
tests/test_config.py::test_shipped_configs_are_valid[config.demo.toml] PASSED [  1%]
tests/test_config.py::test_defaults PASSED                               [  2%]
tests/test_config.py::test_relative_paths_are_relative_to_config_folder PASSED [  3%]
tests/test_config.py::test_missing_file_and_bad_syntax PASSED            [  4%]
tests/test_config.py::test_typo_in_key_is_reported PASSED                [  4%]
tests/test_config.py::test_unknown_section_is_reported PASSED            [  5%]
tests/test_config.py::test_wrong_types_and_ranges PASSED                 [  6%]
tests/test_config.py::test_bool_is_not_accepted_as_number PASSED         [  7%]
tests/test_config.py::test_invalid_choice PASSED                         [  8%]
tests/test_config.py::test_invalid_url PASSED                            [  9%]
tests/test_config.py::test_invalid_timezone PASSED                       [  9%]
tests/test_config.py::test_target_validation PASSED                      [ 10%]
tests/test_config.py::test_no_targets PASSED                             [ 11%]
tests/test_config.py::test_no_match_state_cannot_collide_with_target_state PASSED [ 12%]
tests/test_config.py::test_http_method_limits PASSED                     [ 13%]
tests/test_config.py::test_no_change_cannot_be_recorded PASSED           [ 14%]
tests/test_config.py::test_fingerprint_depends_on_what_is_observed_not_on_interval PASSED [ 14%]
tests/test_config.py::test_all_problems_reported_together PASSED         [ 15%]
tests/test_event_logger.py::test_creates_missing_folders_and_file_with_bom_and_header PASSED [ 16%]
tests/test_event_logger.py::test_rows_contain_required_fields_and_accents PASSED [ 17%]
tests/test_event_logger.py::test_restart_appends_and_keeps_history PASSED [ 18%]
tests/test_event_logger.py::test_refuses_file_with_other_columns_and_leaves_it_untouched PASSED [ 19%]
tests/test_event_logger.py::test_refuses_file_saved_with_another_encoding PASSED [ 19%]
tests/test_event_logger.py::test_refuses_changing_delimiter_of_existing_file PASSED [ 20%]
tests/test_event_logger.py::test_semicolon_delimiter PASSED              [ 21%]
tests/test_event_logger.py::test_parent_path_is_a_file_gives_clear_error PASSED [ 22%]
tests/test_event_logger.py::test_second_monitor_on_same_csv_is_rejected PASSED [ 23%]
tests/test_event_logger.py::test_write_error_keeps_rows_pending_and_retries PASSED [ 23%]
tests/test_event_logger.py::test_unsaved_rows_are_returned_on_close PASSED [ 24%]
tests/test_event_logger.py::test_incomplete_last_line_is_repaired PASSED [ 25%]
tests/test_event_logger.py::test_record_events_filter PASSED             [ 26%]
tests/test_event_logger.py::test_page_text_cannot_become_an_excel_formula PASSED [ 27%]
tests/test_event_logger.py::test_local_time_follows_configured_timezone[America/Lima-when0-2026-01-15T07:00:00.000-05:00] PASSED [ 28%]
tests/test_event_logger.py::test_local_time_follows_configured_timezone[America/Lima-when1-2026-07-15T07:00:00.000-05:00] PASSED [ 28%]
tests/test_event_logger.py::test_local_time_follows_configured_timezone[Europe/Madrid-when2-2026-01-15T13:00:00.000+01:00] PASSED [ 29%]
tests/test_event_logger.py::test_local_time_follows_configured_timezone[Europe/Madrid-when3-2026-07-15T14:00:00.000+02:00] PASSED [ 30%]
tests/test_event_logger.py::test_local_time_follows_configured_timezone[UTC-when4-2026-07-15T12:00:00.000+00:00] PASSED [ 31%]
tests/test_event_logger.py::test_local_date_changes_at_local_midnight PASSED [ 32%]
tests/test_integration_browser.py::test_reload_each_check_sees_server_changes PASSED [ 33%]
tests/test_integration_browser.py::test_without_reload_reads_live_javascript_updates PASSED [ 33%]
tests/test_integration_browser.py::test_placeholder_is_read_unless_settle_time_is_configured PASSED [ 34%]
tests/test_integration_browser.py::test_text_inside_iframe PASSED        [ 35%]
tests/test_integration_browser.py::test_hidden_text_only_counts_with_text_source_all PASSED [ 36%]
tests/test_integration_browser.py::test_missing_element_is_not_an_error PASSED [ 37%]
tests/test_integration_browser.py::test_http_503_is_error_and_reading_recovers PASSED [ 38%]
tests/test_integration_browser.py::test_server_down_and_back PASSED      [ 38%]
tests/test_integration_browser.py::test_browser_crash_is_recovered_by_relaunching PASSED [ 39%]
tests/test_integration_browser.py::test_persistent_profile_keeps_cookies_between_runs PASSED [ 40%]
tests/test_integration_browser.py::test_missing_executable_gives_clear_message PASSED [ 41%]
tests/test_integration_browser.py::test_probe_on_demo_page PASSED        [ 42%]
tests/test_integration_browser.py::test_full_program_browser_mode_stops_cleanly_on_sigint PASSED [ 42%]
tests/test_integration_http.py::test_reads_server_rendered_text PASSED   [ 43%]
tests/test_integration_http.py::test_javascript_text_is_not_visible_without_browser_and_accents_survive PASSED [ 44%]
tests/test_integration_http.py::test_missing_element PASSED              [ 45%]
tests/test_integration_http.py::test_http_error_status_is_error PASSED   [ 46%]
tests/test_integration_http.py::test_connection_refused_is_error PASSED  [ 47%]
tests/test_integration_http.py::test_charset_from_headers PASSED         [ 47%]
tests/test_integration_http.py::test_full_program_http_mode_stops_cleanly_on_sigint PASSED [ 48%]
tests/test_monitor.py::test_session_markers_and_basic_cycle PASSED       [ 49%]
tests/test_monitor.py::test_fixed_rate_schedule_does_not_drift PASSED    [ 50%]
tests/test_monitor.py::test_slow_observation_skips_missed_ticks_instead_of_bursting PASSED [ 51%]
tests/test_monitor.py::test_backoff_after_consecutive_errors PASSED      [ 52%]
tests/test_monitor.py::test_stops_after_max_consecutive_errors PASSED    [ 52%]
tests/test_monitor.py::test_ctrl_c_during_observation_finishes_it_and_closes_cleanly PASSED [ 53%]
tests/test_monitor.py::test_error_caused_by_shutdown_is_not_recorded PASSED [ 54%]
tests/test_monitor.py::test_keyboard_interrupt_still_writes_stop_marker PASSED [ 55%]
tests/test_monitor.py::test_restart_resumes_without_duplicating_events PASSED [ 56%]
tests/test_monitor.py::test_resume_disabled_sets_new_baseline PASSED     [ 57%]
tests/test_monitor.py::test_csv_write_failure_is_retried_on_next_cycle PASSED [ 57%]
tests/test_monitor.py::test_detector_failure_is_an_error_not_a_change PASSED [ 58%]
tests/test_monitor.py::test_gap_in_wall_clock_is_reported PASSED         [ 59%]
tests/test_state_machine.py::test_text_present_from_first_observation_only_sets_baseline PASSED [ 60%]
tests/test_state_machine.py::test_baseline_with_confirmation_needs_n_equal_observations PASSED [ 61%]
tests/test_state_machine.py::test_text_appears PASSED                    [ 61%]
tests/test_state_machine.py::test_text_disappears PASSED                 [ 62%]
tests/test_state_machine.py::test_text_replaced_by_another PASSED        [ 63%]
tests/test_state_machine.py::test_replacement_by_unconfigured_text_keeps_excerpt PASSED [ 64%]
tests/test_state_machine.py::test_no_change_produces_no_events PASSED    [ 65%]
tests/test_state_machine.py::test_change_confirmed_after_two_consecutive_observations PASSED [ 66%]
tests/test_state_machine.py::test_single_flicker_is_filtered PASSED      [ 66%]
tests/test_state_machine.py::test_alternating_candidates_restart_the_count PASSED [ 67%]
tests/test_state_machine.py::test_unknown_reading_keeps_state_and_is_recorded_once PASSED [ 68%]
tests/test_state_machine.py::test_unknown_policy_ignore_keeps_pending_count PASSED [ 69%]
tests/test_state_machine.py::test_unknown_policy_reset_requires_strictly_consecutive_observations PASSED [ 70%]
tests/test_state_machine.py::test_connection_error_is_not_a_disappearance PASSED [ 71%]
tests/test_state_machine.py::test_error_before_any_baseline_does_not_create_state PASSED [ 71%]
tests/test_state_machine.py::test_restart_with_same_state_records_nothing PASSED [ 72%]
tests/test_state_machine.py::test_restart_detects_change_that_happened_while_stopped PASSED [ 73%]
tests/test_state_machine.py::test_restart_ignores_state_saved_with_other_configuration PASSED [ 74%]
tests/test_state_machine.py::test_corrupt_state_file_is_ignored PASSED   [ 75%]
tests/test_state_machine.py::test_recovery_keeps_baseline_and_reports_change_window PASSED [ 76%]
tests/test_state_machine.py::test_recovery_with_rebaseline_policy_records_new_baseline_not_a_change PASSED [ 76%]
tests/test_state_machine.py::test_no_duplicate_events_over_long_sequence PASSED [ 77%]
tests/test_state_machine.py::test_event_ids_are_unique PASSED            [ 78%]
tests/test_state_machine.py::test_independent_texts_with_combined_policy PASSED [ 79%]
tests/test_state_machine.py::test_conflicting_texts_never_confirm_a_change PASSED [ 80%]
tests/test_text_detector.py::test_insensitive_by_default_and_keeps_page_spelling PASSED [ 80%]
tests/test_text_detector.py::test_case_sensitive_global PASSED           [ 81%]
tests/test_text_detector.py::test_case_sensitive_per_target_overrides_global PASSED [ 82%]
tests/test_text_detector.py::test_whitespace_collapse_handles_newlines_tabs_nbsp_and_zero_width PASSED [ 83%]
tests/test_text_detector.py::test_whitespace_exact_requires_identical_spacing PASSED [ 84%]
tests/test_text_detector.py::test_unicode_normalization_nfc PASSED       [ 85%]
tests/test_text_detector.py::test_word_mode_avoids_substring_trap PASSED [ 85%]
tests/test_text_detector.py::test_contains_mode_substring_produces_conflict_and_config_warning PASSED [ 86%]
tests/test_text_detector.py::test_exact_mode_compares_whole_element_text PASSED [ 87%]
tests/test_text_detector.py::test_regex_mode PASSED                      [ 88%]
tests/test_text_detector.py::test_multiple_states_conflict_is_unknown PASSED [ 89%]
tests/test_text_detector.py::test_multiple_states_priority_uses_config_order PASSED [ 90%]
tests/test_text_detector.py::test_multiple_states_combined PASSED        [ 90%]
tests/test_text_detector.py::test_synonyms_map_to_same_state_without_conflict PASSED [ 91%]
tests/test_text_detector.py::test_no_target_present_gives_no_match_state PASSED [ 92%]
tests/test_text_detector.py::test_no_target_present_can_be_unknown PASSED [ 93%]
tests/test_text_detector.py::test_hidden_element_is_read_as_empty_text_which_means_absent PASSED [ 94%]
tests/test_text_detector.py::test_element_missing_is_unknown_by_default PASSED [ 95%]
tests/test_text_detector.py::test_element_missing_can_mean_absent PASSED [ 95%]
tests/test_text_detector.py::test_read_error_is_error_not_absence PASSED [ 96%]
tests/test_text_detector.py::test_match_policy_single_rejects_several_elements PASSED [ 97%]
tests/test_text_detector.py::test_match_policy_first PASSED              [ 98%]
tests/test_text_detector.py::test_match_policy_all_with_exact_checks_each_element PASSED [ 99%]
tests/test_text_detector.py::test_excerpt_is_truncated_and_can_be_disabled PASSED [100%]

============================= 121 passed in 23.81s =============================
```

## Ejecución de extremo a extremo con la demostración

Con la versión final del código se ejecutó el programa completo (`python main.py --config … run`) contra
`demo-server --periodo 12 --con-errores` durante unos 90 segundos. Después se detuvo el servidor y se
envió SIGINT al grupo de procesos del monitor, como hace Ctrl+C en la terminal. El CSV resultante tenía
23 filas, todas con las 24 columnas:

```
10:40:30 MONITOR_STARTED
10:40:36 BASELINE          -> online            (2 observaciones)
10:40:51 TEXT_DISAPPEARED  online -> offline    (2 observaciones, mismo id_transicion)
10:40:51 TEXT_APPEARED     online -> offline
10:40:51 STATE_CHANGED     online -> offline
10:40:56 ERROR             el servidor respondió HTTP 503 (una sola fila por episodio)
10:41:01 RECOVERED         lectura restablecida tras 1 observaciones no válidas
10:41:06 TEXT_DISAPPEARED / TEXT_APPEARED / STATE_CHANGED   offline -> online
   … (el mismo ciclo se repite) …
10:41:56 ERROR             Page.reload: net::ERR_CONNECTION_REFUSED (servidor detenido)
10:41:56 MONITOR_STOPPED   detenido por el usuario (Ctrl+C)
```

El programa terminó con código 0 y no quedó ningún proceso de Chromium abierto. Las horas son de
America/Lima.
