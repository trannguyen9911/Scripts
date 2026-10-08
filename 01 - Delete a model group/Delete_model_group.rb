# encoding: utf-8
# =============================================================================
# Permanently delete a Model Group (InfoWorks ICM)
# =============================================================================
#
# Open the database in InfoWorks ICM, run this script, pick a model group, and
# confirm. The selected group and everything under it is removed permanently
# (not placed in the Recycle Bin). Items already in the Recycle Bin are not listed.
#
# =============================================================================

require 'json'
require 'fileutils'
require 'tmpdir'

SCRIPT_PATH = File.expand_path(__FILE__)

# --- CONFIGURATION ---
# true = preview only (no deletion)
DRY_RUN = false
# If deletion fails in the UI session, retry using the background exchange process.
USE_EXCHANGE_FALLBACK = true
# Optional full path to ICMExchange.exe when auto-detect fails.
ICM_EXCHANGE_PATH = nil
# false = quiet; true = write details to Script Output (support / troubleshooting)
VERBOSE = false
# --- END CONFIGURATION ---

def log_msg(message)
  puts message.to_s if VERBOSE
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

def walk_live_model_groups(mo, acc)
  return if mo.nil?
  return if recycle_bin_subtree?(mo)

  acc << mo if mo.type.to_s == 'Model Group'
  mo.children.each { |child| walk_live_model_groups(child, acc) }
rescue StandardError
end

def collect_live_model_groups(db)
  groups = []
  db.root_model_objects.each do |root|
    next if recycle_bin_subtree?(root)

    walk_live_model_groups(root, groups)
  end
  seen = {}
  groups.select { |g| seen[g.id] ? false : (seen[g.id] = true) }
        .sort_by { |g| g.id.to_i }
end

def model_group_list_label(mo)
  "#{icm_utf8(mo.name)} | ID #{mo.id}"
end

def parse_model_group_id_from_selection(selected)
  s = icm_utf8(selected)
  m = s.match(/\|\s*ID\s*(\d+)\s*\z/i)
  m ? m[1].to_i : nil
end

def entry_for_group_selection(groups, selected)
  gid = parse_model_group_id_from_selection(selected)
  if gid
    match = groups.find { |g| g.id.to_i == gid }
    return match if match
  end
  groups.find { |g| model_group_list_label(g) == icm_utf8(selected) }
end

def count_descendants(mo)
  count = 0
  walk = lambda do |node|
    return if node.nil?

    node.children.each do |child|
      count += 1
      walk.call(child)
    end
  rescue StandardError
  end
  walk.call(mo)
  count
end

def permanent_bulk_delete(mo)
  mo.bulk_delete
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

def delete_job_file?(path)
  return false unless path && File.file?(path.to_s)

  job = JSON.parse(File.read(path))
  job.is_a?(Hash) && job.key?('model_group_id') && (job.key?('database_guid') || job.key?('database_path'))
rescue StandardError
  false
end

def running_exchange_job?
  path = export_job_path_from_argv
  return false if path.nil?

  running_via_icm_exchange? || delete_job_file?(path)
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
  db ||= WSApplication.current_database
  db ||= WSApplication.open
  raise 'Could not open the database.' if db.nil?

  expected = job['database_guid']
  if expected && db.respond_to?(:guid) && db.guid.to_s != expected.to_s
    raise 'The exchange process connected to a different database than the one open in ICM.'
  end
  db
end

def resolve_model_group(db, group_id)
  mo = db.model_object_from_type_and_id('Model Group', group_id)
  return mo if mo && !recycle_bin_subtree?(mo)

  collect_live_model_groups(db).find { |g| g.id.to_i == group_id.to_i }
end

def run_delete_job(job)
  dry_run = job['dry_run'] ? true : false
  group_id = job['model_group_id'].to_i
  log_msg("Background delete: model group ID #{group_id}, dry_run=#{dry_run}")

  db = open_db_from_job(job)
  group = resolve_model_group(db, group_id)
  raise "Model group ID #{group_id} was not found in the database." if group.nil?

  label = model_group_list_label(group)
  if dry_run
    log_msg("Dry run — would delete: #{label}")
    return true
  end

  permanent_bulk_delete(group)
  log_msg("Deleted: #{label}")
  db.close if db.respond_to?(:close)
  true
rescue StandardError => e
  log_msg("Error: #{e.message}")
  false
end

def write_delete_job(db, group_id, dry_run)
  staging = File.join(Dir.tmpdir, 'icm_model_group_delete_jobs', "delete_#{Process.pid}_#{Time.now.strftime('%Y%m%d_%H%M%S')}")
  FileUtils.mkdir_p(staging)
  job = {
    'database_guid' => db.guid,
    'database_path' => database_path_for(db),
    'model_group_id' => group_id,
    'dry_run' => dry_run ? true : false
  }
  job_path = File.join(staging, 'job.json')
  File.open(job_path, 'w:UTF-8') { |f| f.write(JSON.pretty_generate(job)) }
  { job_path: job_path, staging: staging }
end

def launch_exchange_delete(job_bundle)
  exchange = find_icm_exchange
  if exchange.nil?
    icm_message_box(
      'Could not locate ICMExchange.exe on this computer. Set ICM_EXCHANGE_PATH at the top of the script, or install/repair InfoWorks ICM.',
      'OK',
      '!'
    )
    return false
  end

  command = build_exchange_launch_command(exchange, SCRIPT_PATH, job_bundle[:job_path])
  log_msg("Starting background delete: #{command}")
  success = false
  require 'open3'
  Open3.popen2e(command) do |_stdin, stdout_and_stderr, wait_thr|
    stdout_and_stderr.each { |line| log_msg(line.chomp) }
    success = wait_thr.value.success?
    log_msg("Background process exit code: #{wait_thr.value.exitstatus}")
  end
  success
rescue StandardError => e
  log_msg("Background delete failed: #{e.message}")
  false
ensure
  FileUtils.rm_rf(job_bundle[:staging]) if job_bundle[:staging]
end

def delete_model_group_in_process(group, dry_run)
  label = model_group_list_label(group)
  if dry_run
    log_msg("Dry run — would delete: #{label}")
    return { ok: true }
  end

  permanent_bulk_delete(group)
  log_msg("Deleted: #{label}")
  { ok: true }
rescue StandardError => e
  log_msg("Delete failed: #{e.message}")
  { ok: false, error: e.message }
end

def run_from_ui
  db = WSApplication.current_database
  if db.nil?
    icm_message_box('Open a database in InfoWorks ICM, then run this script again.', 'OK', '!')
    return
  end

  groups = collect_live_model_groups(db)
  if groups.empty?
    icm_message_box('No model groups were found in this database.', 'OK', '!')
    return
  end

  choices = groups.map { |g| model_group_list_label(g) }
  result = WSApplication.prompt(
    'Delete model group permanently',
    [
      ['Model group', 'String', choices.first, nil, 'LIST', choices]
    ],
    false
  )
  return if result.nil?

  group = entry_for_group_selection(groups, result[0])
  if group.nil?
    icm_message_box('The selected model group could not be found. Run the script again.', 'OK', '!')
    return
  end

  child_count = count_descendants(group)
  selection_label = model_group_list_label(group)

  if DRY_RUN
    confirm = icm_message_box(
      "Dry run (no changes will be made)\n\n" \
      "#{selection_label}\n" \
      "Child items under this group (approx.): #{child_count}\n\n" \
      'Continue?',
      'YesNo',
      '?'
    )
    return unless confirm == 'Yes'

    delete_model_group_in_process(group, true)
    icm_message_box(
      "Dry run complete.\n\nNo data was deleted.\n\n#{selection_label}",
      'OK',
      'Information'
    )
    return
  end

  confirm = icm_message_box(
    "Permanently delete this model group?\n\n" \
    "#{selection_label}\n" \
    "All networks, runs, simulations, and other items under this group will also be removed (#{child_count} child object(s), approx.).\n\n" \
    "This action cannot be undone.\n\n" \
    'Do you want to continue?',
    'YesNo',
    '?'
  )
  return unless confirm == 'Yes'

  outcome = delete_model_group_in_process(group, false)
  if !outcome[:ok] && USE_EXCHANGE_FALLBACK
    log_msg('Retrying using background exchange process...')
    job_bundle = write_delete_job(db, group.id, false)
    exchange_ok = launch_exchange_delete(job_bundle)
    unless exchange_ok
      icm_message_box(
        "The model group could not be deleted.\n\nTurn on VERBOSE in the script and check Script Output for details.",
        'OK',
        '!'
      )
      return
    end
  elsif !outcome[:ok]
    icm_message_box(
      "The model group could not be deleted.\n\n#{outcome[:error]}",
      'OK',
      '!'
    )
    return
  end

  icm_message_box(
    "The model group was deleted permanently.\n\n#{selection_label}",
    'OK',
    'Information'
  )
end

if running_exchange_job?
  job_path = export_job_path_from_argv
  success = run_delete_job(JSON.parse(File.read(job_path)))
  exit(success ? 0 : 1)
end

run_from_ui
