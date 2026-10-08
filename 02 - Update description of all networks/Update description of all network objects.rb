# encoding: utf-8
# =============================================================================
# Update model network descriptions (InfoWorks ICM)
# =============================================================================
#
# For every model network in the open database, sets the Description field to:
#   Network version [latest commit ID]. Comment: [that commit's message]
#
# Run from Network → Run Ruby script with the correct database open.
# The UI session starts ICMExchange automatically (required for commit history).
#
# =============================================================================

require 'json'
require 'fileutils'
require 'tmpdir'

SCRIPT_PATH = File.expand_path(__FILE__)

# --- CONFIGURATION (optional — most users can leave defaults) ---
# true = preview only; no Description changes are written
DRY_RUN = false
# Full path to ICMExchange.exe if the script cannot find it automatically
ICM_EXCHANGE_PATH = nil
# true = list each network in Script Output (support / troubleshooting)
VERBOSE = false
# For running this file directly via ICMExchange only (not from the ICM UI)
DATABASE_PATH = nil
# --- END CONFIGURATION ---

RESULT_MARKER = '__ICM_NETWORK_DESC_RESULT__'

def log_msg(message)
  puts message.to_s if VERBOSE
end

def format_duration(seconds)
  s = seconds.to_f
  return 'less than 1 second' if s < 1.0
  return "#{s.round(1)} seconds" if s < 60.0

  mins = (s / 60).floor
  secs = (s % 60).round
  "#{mins} min #{secs} sec"
end

def emit_result_payload(results, dry_run, elapsed_sec)
  payload = {
    'dry_run' => dry_run ? true : false,
    'elapsed_sec' => elapsed_sec.to_f.round(3),
    'total' => results[:total],
    'updated' => results[:updated],
    'skipped' => results[:skipped],
    'failed' => results[:failed]
  }
  puts "#{RESULT_MARKER}#{JSON.generate(payload)}"
end

def parse_result_payload_from_output(output_lines)
  Array(output_lines).each do |line|
    text = line.to_s
    next unless text.start_with?(RESULT_MARKER)

    return JSON.parse(text.sub(RESULT_MARKER, ''))
  end
  nil
rescue StandardError
  nil
end

def build_completion_message(payload, elapsed_sec)
  time_str = format_duration(elapsed_sec)
  if payload.nil?
    return "The update step finished.\n\nTime taken: #{time_str}\n\nOpen Script Output for details."
  end

  dry_run = payload['dry_run'] ? true : false
  heading = dry_run ? 'Preview finished' : 'Update finished'
  updated_label = dry_run ? 'Would update' : 'Updated'
  failed = payload['failed'].to_i

  lines = [
    heading,
    '',
    "Model networks in database: #{payload['total']}",
    "#{updated_label}: #{payload['updated']}",
    "Unchanged (already up to date): #{payload['skipped']}",
    "Could not update: #{failed}",
    '',
    "Time taken: #{time_str}"
  ]
  lines << ''
  lines << 'Set VERBOSE = true at the top of the script for a per-network log in Script Output.'
  lines << 'Refresh the database tree if descriptions do not appear immediately.' if failed.zero? && !dry_run
  lines.join("\n")
end

def icm_message_box(text, buttons = 'OK', icon = nil)
  WSApplication.message_box(text.to_s, buttons, icon, false)
end

def icm_utf8(text)
  raw = text.nil? ? '' : text.to_s
  utf8 = raw.dup
  utf8 = utf8.force_encoding(Encoding::UTF_8) if utf8.encoding != Encoding::UTF_8
  return utf8 if utf8.valid_encoding?

  raw.encode(Encoding::UTF_8, invalid: :replace, undef: :replace, replace: '?')
rescue StandardError
  raw.to_s
end

def recycle_bin_subtree?(mo)
  return false if mo.nil?

  path = mo.path.to_s.sub(/\A>/, '').strip
  return true if path.casecmp('Recycle Bin').zero?
  return true if path.start_with?('Recycle Bin>')

  mo.name.to_s.strip.casecmp('Recycle Bin').zero?
rescue StandardError
  false
end

def walk_live_model_networks(mo, acc)
  return if mo.nil?
  return if recycle_bin_subtree?(mo)

  acc << mo if mo.type.to_s == 'Model Network'
  mo.children.each { |child| walk_live_model_networks(child, acc) }
rescue StandardError
end

def collect_live_model_networks(db)
  networks = []

  if db.respond_to?(:model_object_collection)
    begin
      db.model_object_collection('Model Network').each do |net|
        next if recycle_bin_subtree?(net)

        networks << net
      end
    rescue StandardError => e
      log_msg("model_object_collection fallback: #{e.message}")
    end
  end

  if networks.empty?
    db.root_model_objects.each do |root|
      next if recycle_bin_subtree?(root)

      walk_live_model_networks(root, networks)
    end
  end

  seen = {}
  networks.select { |n| seen[n.id] ? false : (seen[n.id] = true) }
          .sort_by { |n| [n.id.to_i, icm_utf8(n.name)] }
end

def network_list_label(mo)
  "#{icm_utf8(mo.name)} | ID #{mo.id}"
end

def format_network_description(version_no, commit_message)
  version_label = version_no.nil? ? 'n/a' : version_no.to_s
  comment_body = icm_utf8(commit_message).strip
  "Network version #{version_label}. Comment: #{comment_body}"
end

def latest_version_number(net_mo)
  return net_mo.latest_commit_id if net_mo.respond_to?(:latest_commit_id)

  nil
rescue StandardError => e
  log_msg("  latest_commit_id unavailable for ID #{net_mo.id}: #{e.message}")
  nil
end

def read_network_description(net_mo)
  return icm_utf8(net_mo.comment) if net_mo.respond_to?(:comment)

  ''
rescue StandardError => e
  log_msg("  description read failed for ID #{net_mo.id}: #{e.message}")
  ''
end

def latest_commit_message(net_mo, version_no)
  return '' if version_no.nil?
  return '' unless net_mo.respond_to?(:commits)

  message = nil
  net_mo.commits.each do |commit|
    next unless commit.commit_id == version_no

    message = commit.comment if commit.respond_to?(:comment)
    break
  end
  icm_utf8(message || '')
rescue StandardError => e
  log_msg("  commit history unavailable for ID #{net_mo.id}: #{e.message}")
  ''
end

def write_network_comment(net_mo, text)
  if net_mo.respond_to?(:comment=)
    net_mo.comment = icm_utf8(text)
    return true
  end

  false
rescue StandardError => e
  log_msg("  comment write failed for ID #{net_mo.id}: #{e.message}")
  false
end

def update_network_descriptions(db, dry_run)
  networks = collect_live_model_networks(db)
  results = {
    total: networks.length,
    updated: 0,
    skipped: 0,
    failed: 0,
    lines: []
  }

  networks.each do |net_mo|
    label = network_list_label(net_mo)
    version_no = latest_version_number(net_mo)
    commit_message = latest_commit_message(net_mo, version_no)
    new_description = format_network_description(version_no, commit_message)
    current_description = read_network_description(net_mo)

    if icm_utf8(current_description) == icm_utf8(new_description)
      results[:skipped] += 1
      line = "Unchanged: #{label}"
      results[:lines] << line
      log_msg(line)
      next
    end

    if dry_run
      results[:updated] += 1
      line = "Preview — would update: #{label} (version #{version_no.nil? ? 'n/a' : version_no})"
      results[:lines] << line
      log_msg(line)
      next
    end

    if write_network_comment(net_mo, new_description)
      results[:updated] += 1
      line = "Updated: #{label} (version #{version_no.nil? ? 'n/a' : version_no})"
      results[:lines] << line
      log_msg(line)
    else
      results[:failed] += 1
      line = "Failed: #{label}"
      results[:lines] << line
      log_msg(line)
    end
  end

  results
end

def database_path_for(db)
  %i[path database_path location file_path].each do |meth|
    next unless db.respond_to?(meth)

    val = db.send(meth).to_s.strip
    return val unless val.empty?
  end
  nil
rescue StandardError
  nil
end

def exchange_argv_token_skip?(arg)
  a = arg.to_s
  return true if a =~ /\A\//
  return true if %w[ADSK ICM IA WS Autodesk].include?(a)

  false
end

def running_via_icm_exchange?
  first = ARGV[0].to_s
  return true if first == 'ADSK'
  return true if first == 'ICM'

  ARGV.any? { |a| a.to_s =~ /\A\/ICM/i }
end

def export_job_path_from_argv
  ARGV.each do |arg|
    next if exchange_argv_token_skip?(arg)

    path = arg.to_s
    return path if path.end_with?('.json') && File.file?(path)
  end
  nil
end

def update_job_file?(path)
  return false unless path && File.file?(path.to_s)

  job = JSON.parse(File.read(path))
  job.is_a?(Hash) && job['action'] == 'update_network_descriptions'
rescue StandardError
  false
end

def running_exchange_job?
  path = export_job_path_from_argv
  return false if path.nil?

  running_via_icm_exchange? || update_job_file?(path)
end

def find_icm_exchange
  if ICM_EXCHANGE_PATH && !ICM_EXCHANGE_PATH.to_s.strip.empty?
    path = File.expand_path(ICM_EXCHANGE_PATH.to_s)
    return path if File.file?(path)
  end

  patterns = [
    'C:/Program Files/Autodesk/InfoWorks ICM Ultimate */ICMExchange.exe',
    'C:/Program Files/Autodesk/InfoWorks ICM */ICMExchange.exe'
  ]
  paths = []
  patterns.each { |pattern| paths.concat(Dir.glob(pattern.tr('\\', '/'))) }
  paths.uniq.select { |p| File.file?(p) }.sort.reverse.first
rescue StandardError
  nil
end

def build_exchange_launch_command(exchange_path, script_path, job_path)
  "\"#{exchange_path}\" \"#{script_path}\" \"#{job_path}\""
end

def open_db_from_job(job)
  db_path = job['database_path'].to_s.strip
  db = nil
  unless db_path.empty?
    begin
      log_msg("Opening database: #{db_path}")
      db = WSApplication.open(db_path, false)
    rescue StandardError => e
      log_msg("Could not open database: #{e.message}")
    end
  end
  db ||= WSApplication.current_database if WSApplication.ui?
  db ||= WSApplication.open
  raise 'Could not open the database.' if db.nil?

  expected = job['database_guid']
  if expected && db.respond_to?(:guid) && db.guid.to_s != expected.to_s
    raise 'The exchange process connected to a different database than the one open in ICM.'
  end
  db
end

def open_db_for_direct_exchange
  path = DATABASE_PATH.to_s.strip
  return WSApplication.open(path, false) unless path.empty?

  WSApplication.open
end

def write_update_job(db, dry_run)
  staging = File.join(
    Dir.tmpdir,
    'icm_update_network_description_jobs',
    "update_#{Process.pid}_#{Time.now.strftime('%Y%m%d_%H%M%S')}"
  )
  FileUtils.mkdir_p(staging)
  job = {
    'action' => 'update_network_descriptions',
    'database_guid' => db.guid,
    'database_path' => database_path_for(db),
    'dry_run' => dry_run ? true : false
  }
  job_path = File.join(staging, 'job.json')
  File.open(job_path, 'w:UTF-8') { |f| f.write(JSON.pretty_generate(job)) }
  { job_path: job_path, staging: staging }
end

def launch_exchange_update(job_bundle)
  exchange = find_icm_exchange
  if exchange.nil?
    icm_message_box(
      "ICMExchange could not be found on this computer.\n\n" \
      "Set ICM_EXCHANGE_PATH at the top of the script, or repair your InfoWorks ICM installation.",
      'OK',
      '!'
    )
    return { ok: false, elapsed_sec: 0.0, payload: nil, output_lines: [] }
  end

  command = build_exchange_launch_command(exchange, SCRIPT_PATH, job_bundle[:job_path])
  log_msg("Starting background update: #{command}")
  success = false
  output_lines = []
  started = Process.clock_gettime(Process::CLOCK_MONOTONIC)
  require 'open3'
  Open3.popen2e(command) do |_stdin, stdout_and_stderr, wait_thr|
    stdout_and_stderr.each do |line|
      text = line.chomp
      output_lines << text
      puts text
      log_msg(text) if VERBOSE
    end
    success = wait_thr.value.success?
    puts "Background process exit code: #{wait_thr.value.exitstatus}"
  end
  elapsed_sec = Process.clock_gettime(Process::CLOCK_MONOTONIC) - started
  payload = parse_result_payload_from_output(output_lines)
  { ok: success, elapsed_sec: elapsed_sec, payload: payload, output_lines: output_lines }
rescue StandardError => e
  log_msg("Background update failed: #{e.message}")
  { ok: false, elapsed_sec: 0.0, payload: nil, output_lines: [] }
ensure
  FileUtils.rm_rf(job_bundle[:staging]) if job_bundle[:staging]
end

def summarize_results(results, dry_run, elapsed_sec: nil)
  action = dry_run ? 'Preview complete' : 'Update complete'
  updated_label = dry_run ? 'Would update' : 'Updated'
  sample = results[:lines].first(8).join("\n")
  more = results[:lines].length > 8 ? "\n… (#{results[:lines].length - 8} more lines with VERBOSE = true)" : ''
  time_line = elapsed_sec ? "\nTime taken: #{format_duration(elapsed_sec)}" : ''

  "#{action}\n\n" \
    "Model networks in database: #{results[:total]}\n" \
    "#{updated_label}: #{results[:updated]}\n" \
    "Unchanged (already up to date): #{results[:skipped]}\n" \
    "Could not update: #{results[:failed]}" \
    "#{time_line}\n\n" \
    "#{sample}#{more}"
end

def run_update_job(job)
  dry_run = job['dry_run'] ? true : false
  log_msg("Background update network descriptions, dry_run=#{dry_run}")

  started = Process.clock_gettime(Process::CLOCK_MONOTONIC)
  db = open_db_from_job(job)
  results = update_network_descriptions(db, dry_run)
  elapsed_sec = Process.clock_gettime(Process::CLOCK_MONOTONIC) - started
  puts summarize_results(results, dry_run, elapsed_sec: elapsed_sec)
  emit_result_payload(results, dry_run, elapsed_sec)
  db.close if db.respond_to?(:close)
  results[:failed].zero?
rescue StandardError => e
  log_msg("Error: #{e.message}")
  puts "Update failed: #{e.message}"
  false
end

def run_from_ui
  unless WSApplication.ui?
    db = open_db_for_direct_exchange
    raise 'Could not open the database.' if db.nil?

    started = Process.clock_gettime(Process::CLOCK_MONOTONIC)
    results = update_network_descriptions(db, DRY_RUN)
    elapsed_sec = Process.clock_gettime(Process::CLOCK_MONOTONIC) - started
    puts summarize_results(results, DRY_RUN, elapsed_sec: elapsed_sec)
    emit_result_payload(results, DRY_RUN, elapsed_sec)
    db.close if db.respond_to?(:close)
    return
  end

  run_started = Process.clock_gettime(Process::CLOCK_MONOTONIC)

  db = WSApplication.current_database
  if db.nil?
    icm_message_box('Open your project database in InfoWorks ICM, then run this script again.', 'OK', '!')
    return
  end

  networks = collect_live_model_networks(db)
  if networks.empty?
    icm_message_box('No model networks were found in this database.', 'OK', '!')
    return
  end

  db_label = icm_utf8(database_path_for(db) || db.path)
  mode_label = DRY_RUN ? 'Preview update (no changes will be made)' : 'Update network descriptions'
  confirm = icm_message_box(
    "#{mode_label}\n\n" \
    "Database: #{db_label}\n" \
    "Model networks found: #{networks.length}\n\n" \
    "For each network, the Description field will be set to:\n" \
    "Network version [number]. Comment: [message from the latest commit]\n\n" \
    "Networks already matching that text are left unchanged.\n\n" \
    'Do you want to continue?',
    'YesNo',
    '?'
  )
  return unless confirm == 'Yes'

  job_bundle = write_update_job(db, DRY_RUN)
  exchange_outcome = launch_exchange_update(job_bundle)
  total_elapsed = Process.clock_gettime(Process::CLOCK_MONOTONIC) - run_started

  unless exchange_outcome[:ok]
    icm_message_box(
      "Descriptions could not be updated.\n\n" \
      "Time taken: #{format_duration(total_elapsed)}\n\n" \
      'Set VERBOSE = true and check Script Output for details.',
      'OK',
      '!'
    )
    return
  end

  payload = exchange_outcome[:payload]
  completion_text = build_completion_message(payload, total_elapsed)
  failed_count = payload ? payload['failed'].to_i : 0
  icon = failed_count.positive? ? '!' : 'Information'
  icm_message_box(completion_text, 'OK', icon)
end

if running_exchange_job?
  job_path = export_job_path_from_argv
  success = run_update_job(JSON.parse(File.read(job_path)))
  exit(success ? 0 : 1)
end

run_from_ui
