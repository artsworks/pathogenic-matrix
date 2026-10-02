extends Node
## Pathogenic Matrix observer. Read-only: it reads G.* / SignalBus / the scene
## tree and writes local JSON. It never changes game state.
##
## Outputs (all under user://):
##   matrix_state.json         latest state snapshot, rewritten atomically
##   matrix_catalog.json       live organelle/mutation catalog, once per launch
##   matrix_logs/session_*.jsonl  append-only event log, one file per launch

const MOD_VERSION := "0.1.0"
const SCHEMA := 2
const STATE_PATH := "user://matrix_state.json"
const STATE_TMP_PATH := "user://matrix_state.json.tmp"
const CATALOG_PATH := "user://matrix_catalog.json"
const CONFIG_PATH := "user://matrix_config.json"
const LOG_DIR := "user://matrix_logs"
const LOG := "Artsworks-PathogenicMatrix"

var http_url := "http://127.0.0.1:48710/state"
var http_enabled := true
var file_enabled := true
var log_enabled := true
var poll_interval := 0.25
var heartbeat_interval := 2.0
var max_log_files := 30

var _http: HTTPRequest
var _http_busy := false
var _dirty := true
var _catalog_dumped := false
var _fingerprint := ""
var _since_emit := 0.0

var _log_file: FileAccess
var _session_id := ""
var _presented := {}
var _connected_rewards := {}
var _shop_paid := {}
var _tooltip_cache := {}
var _level_up_choice := {}
var _room := {}
var _death_logged := false


func _ready() -> void:
	_load_config()
	_session_id = str(int(Time.get_unix_time_from_system()))
	if log_enabled:
		_open_log()
	_log_event(
		"session_start",
		{
			"mod_version": MOD_VERSION,
			"schema": SCHEMA,
			"game_version": str(ProjectSettings.get_setting("application/config/version", "")),
			"engine": Engine.get_version_info().get("string", ""),
			"os": OS.get_name(),
			"locale": TranslationServer.get_locale(),
		}
	)
	if http_enabled:
		_http = HTTPRequest.new()
		_http.name = "MatrixHTTP"
		_http.timeout = 1.0
		add_child(_http)
		_http.request_completed.connect(func(_r, _code, _h, _b): _http_busy = false)
	_connect_signals()
	var timer := Timer.new()
	timer.wait_time = poll_interval
	timer.autostart = true
	timer.timeout.connect(_tick)
	add_child(timer)


func _exit_tree() -> void:
	_log_event("session_end", {})
	if _log_file:
		_log_file.close()


func _load_config() -> void:
	if not FileAccess.file_exists(CONFIG_PATH):
		return
	var parsed = JSON.parse_string(FileAccess.get_file_as_string(CONFIG_PATH))
	if parsed is Dictionary:
		http_enabled = parsed.get("http_enabled", http_enabled)
		file_enabled = parsed.get("file_enabled", file_enabled)
		log_enabled = parsed.get("log_enabled", log_enabled)
		http_url = parsed.get("http_url", http_url)
		poll_interval = parsed.get("poll_interval", poll_interval)
		max_log_files = parsed.get("max_log_files", max_log_files)
		ModLoaderLog.info("Loaded config from %s" % CONFIG_PATH, LOG)


# ------------------------------------------------------------------ logging


func _open_log() -> void:
	DirAccess.make_dir_recursive_absolute(LOG_DIR)
	var dir := DirAccess.open(LOG_DIR)
	if dir:
		var files := []
		for f in dir.get_files():
			if f.begins_with("session_") and f.ends_with(".jsonl"):
				files.append(f)
		files.sort()
		while files.size() >= max_log_files:
			dir.remove(files.pop_front())
	_log_file = FileAccess.open(
		LOG_DIR.path_join("session_%s.jsonl" % _session_id), FileAccess.WRITE
	)
	if _log_file == null:
		ModLoaderLog.warning("Could not open session log in %s" % LOG_DIR, LOG)


func _log_event(ev: String, data: Dictionary) -> void:
	if _log_file == null:
		return
	var rec := {"ev": ev, "ts": Time.get_unix_time_from_system(), "session": _session_id}
	rec.merge(data)
	_log_file.store_line(JSON.stringify(rec))
	_log_file.flush()


# ------------------------------------------------------------------ signals


func _connect_signals() -> void:
	var arg_counts := {}
	for s in SignalBus.get_signal_list():
		arg_counts[s.name] = s.args.size()
	var handlers := {
		&"room_started": [_on_room_started, 1],
		&"room_finished": [_on_room_finished, 1],
		&"player_hit": [_on_player_hit, 1],
		&"enemy_died": [_on_enemy_died, 1],
		&"boss_beaten": [_on_boss_beaten, 0],
		&"mutation_chosen": [_on_mutation_chosen, 0],
		&"bodypart_attached": [_on_bodypart_attached, 1],
		&"player_created": [_on_player_created, 1],
		&"next_level_started": [_on_next_level_started, 0],
	}
	var dirty_only := [
		&"bodypart_reward_spawned",
		&"bodypart_detached",
		&"pick_up_taken",
		&"room_entered",
		&"shopkeeper_angered",
		&"parasite_selected",
		&"level_ready",
		&"player_hp_hit",
	]
	for sig in handlers:
		if not SignalBus.has_signal(sig):
			_log_event("signal_missing", {"signal": sig})
			continue
		var cb: Callable = handlers[sig][0]
		var expected: int = handlers[sig][1]
		var actual: int = arg_counts.get(sig, 0)
		if actual == expected:
			SignalBus.connect(sig, cb)
		else:
			_log_event(
				"signal_arity_changed", {"signal": sig, "expected": expected, "actual": actual}
			)
			SignalBus.connect(sig, _mark_dirty.unbind(actual))
	for sig in dirty_only:
		if SignalBus.has_signal(sig):
			SignalBus.connect(sig, _mark_dirty.unbind(arg_counts.get(sig, 0)))
		else:
			_log_event("signal_missing", {"signal": sig})


func _mark_dirty() -> void:
	_dirty = true


func _on_room_started(_room_node) -> void:
	_dirty = true
	var p = G.player
	_room = {
		"room": _room_info(),
		"level_number": G.level_number,
		"t0": Time.get_ticks_msec(),
		"hp_start": p.hp if is_instance_valid(p) else null,
		"max_hp_start": p.max_hp if is_instance_valid(p) else null,
		"hits": 0,
		"damage": 0.0,
		"kills": 0,
	}
	_log_event("room_started", {"room": _room["room"], "level_number": G.level_number})


func _on_room_finished(_room_node) -> void:
	_dirty = true
	if _room.is_empty():
		return
	var p = G.player
	_log_event(
		"room_finished",
		{
			"room": _room["room"],
			"level_number": _room["level_number"],
			"duration_s": (Time.get_ticks_msec() - int(_room["t0"])) / 1000.0,
			"hp_start": _room["hp_start"],
			"hp_end": p.hp if is_instance_valid(p) else null,
			"max_hp_end": p.max_hp if is_instance_valid(p) else null,
			"hits_taken": _room["hits"],
			"damage_taken": _room["damage"],
			"kills": _room["kills"],
		}
	)
	_room = {}


func _on_player_hit(amount) -> void:
	_dirty = true
	if _room.is_empty():
		return
	_room["hits"] += 1
	if amount is float or amount is int:
		_room["damage"] += float(amount)


func _on_enemy_died(_enemy) -> void:
	if not _room.is_empty():
		_room["kills"] += 1


func _on_boss_beaten() -> void:
	_dirty = true
	_log_event("boss_beaten", {"level_number": G.level_number, "room": _room_info()})


func _on_next_level_started() -> void:
	_dirty = true
	_tooltip_cache.clear()
	_log_event("level_started", {"level_number": G.level_number})


func _on_player_created(_player) -> void:
	_dirty = true
	_death_logged = false
	_log_event(
		"player_created",
		{
			"parasite": _parasite_name(),
			"rng_seed": str(G.rng_seed),
			"level_number": G.level_number,
		}
	)


func _on_bodypart_attached(b) -> void:
	_dirty = true
	if not is_instance_valid(b) or not is_instance_valid(b.res):
		return
	_log_event(
		"bodypart_attached",
		{
			"id": _res_id(b.res),
			"rarity": _enum_name(Bodypart.Rarity, b.rarity),
			"slot": b.slot.name if is_instance_valid(b.get("slot")) else null,
		}
	)


func _on_mutation_chosen() -> void:
	_dirty = true
	if _level_up_choice.is_empty():
		_log_event("mutation_chosen", {"taken": _new_mutation_ids([])})
		return
	var added := _new_mutation_ids(_level_up_choice["before"])
	var taken = null
	for opt in _level_up_choice["options"]:
		if opt["id"] in added:
			taken = opt["key"]
	_log_event(
		"choice_taken",
		{
			"choice_id": _level_up_choice["choice_id"],
			"kind": "level_up",
			"taken": taken,
			"added_mutations": added,
		}
	)
	_level_up_choice = {}


func _on_reward_picked(_reward, choice_id: String, key: String) -> void:
	_dirty = true
	_log_event("choice_taken", {"choice_id": choice_id, "kind": "reward", "taken": key})


# --------------------------------------------------------------------- tick


func _tick() -> void:
	if not _catalog_dumped:
		_try_dump_catalog()
	_since_emit += poll_interval
	var fp := _cheap_fingerprint()
	if fp != _fingerprint:
		_fingerprint = fp
		_dirty = true
	if not _dirty and _since_emit < heartbeat_interval:
		return
	_dirty = false
	_since_emit = 0.0
	var state := _build_state()
	_track_choices(state)
	_track_death(state)
	var payload := JSON.stringify(state)
	if file_enabled:
		_write_file(payload)
	if http_enabled and _http and not _http_busy:
		_http_busy = true
		var err := _http.request(
			http_url, ["Content-Type: application/json"], HTTPClient.METHOD_POST, payload
		)
		if err != OK:
			_http_busy = false


func _cheap_fingerprint() -> String:
	var parts := [G.level_number, get_tree().get_nodes_in_group("bodypart_reward").size()]
	var editor = G.editor
	if is_instance_valid(editor) and editor.has_method("is_choosing_mutation"):
		parts.append(editor.is_choosing_mutation())
	var p = G.player
	if is_instance_valid(p):
		parts.append_array([p.level, p.money, p.max_hp, p.mutations.size(), p.dead])
	if is_instance_valid(G.current_room):
		parts.append(G.current_room.get_instance_id())
	return str(parts)


func _write_file(payload: String) -> void:
	var f := FileAccess.open(STATE_TMP_PATH, FileAccess.WRITE)
	if f == null:
		return
	f.store_string(payload)
	f.close()
	if FileAccess.file_exists(STATE_PATH):
		DirAccess.remove_absolute(STATE_PATH)
	DirAccess.rename_absolute(STATE_TMP_PATH, STATE_PATH)


func _track_choices(state: Dictionary) -> void:
	for group in state.get("choices", []):
		var cid: String = group["choice_id"]
		if _presented.has(cid):
			continue
		_presented[cid] = true
		_log_event(
			"choice_presented",
			{
				"choice_id": cid,
				"kind": group["kind"],
				"exclusive": group["exclusive"],
				"options": group["options"],
				"state": state,
			}
		)
		if group["kind"] == "level_up":
			_level_up_choice = {
				"choice_id": cid,
				"options": group["options"],
				"before": _current_mutation_ids(),
			}


func _track_death(state: Dictionary) -> void:
	var p = state.get("player")
	if p == null or not p.get("dead", false) or _death_logged:
		return
	_death_logged = true
	_log_event(
		"run_end",
		{"cause": "death", "level_number": G.level_number, "room": _room_info(), "state": state}
	)


# -------------------------------------------------------------- state build


func _build_state() -> Dictionary:
	var state := {
		"schema": SCHEMA,
		"ts": Time.get_unix_time_from_system(),
		"session": _session_id,
		"mod_version": MOD_VERSION,
		"in_run": false,
		"choices": [],
	}
	state["level_number"] = G.level_number
	state["rng_seed"] = str(G.rng_seed)
	state["parasite"] = _parasite_name()
	if is_instance_valid(G.game_state):
		state["shopkeeper_angered"] = G.game_state.get("is_shopkeeper_angered")
	state["room"] = _room_info()
	var p = G.player
	if is_instance_valid(p):
		state["in_run"] = true
		state["player"] = _serialize_player(p)
	state["choices"] = _collect_choices()
	return state


func _room_info():
	if not is_instance_valid(G.current_room):
		return null
	var room_res = G.current_room.get("res")
	return {
		"name": str(G.current_room.name),
		"type": _enum_name(G.RoomType, room_res.get("type")) if room_res != null else "",
	}


func _serialize_player(p) -> Dictionary:
	return {
		"hp": p.hp,
		"max_hp": p.max_hp,
		"armor": p.armor,
		"level": p.level,
		"dna": p.dna,
		"dna_to_level_up": p.dna_to_level_up(),
		"money": p.money,
		"stamina": p.stamina,
		"max_stamina": p.max_stamina,
		"speed": p.speed,
		"player_damage_mult": p.player_damage_mult,
		"dodge_cd": p.dodge_cd,
		"dodge_invulnerability": p.dodge_invulnerability,
		"pickup_range_mult": p.pickup_range_mult,
		"dead": p.dead,
		"slots": _serialize_slots(p),
		"mutations": _serialize_mutations(p.mutations),
	}


func _serialize_slots(p) -> Array:
	var out := []
	for slot in p.slots:
		if not is_instance_valid(slot):
			continue
		var entry := {
			"slot": str(slot.name),
			"internal": slot.internal,
			"connects_to": [],
			"bodypart": null,
		}
		for s in slot.connections:
			if is_instance_valid(s):
				entry["connects_to"].append(str(s.name))
		var b = slot.bodypart
		if is_instance_valid(b) and is_instance_valid(b.res):
			entry["bodypart"] = {
				"id": _res_id(b.res),
				"name": tr(b.res.ui_name),
				"rarity": _enum_name(Bodypart.Rarity, b.rarity),
				"tags": _tag_names(b.res.tags),
				"energy": b.energy,
				"max_energy": b.max_energy,
				"charge": b.charge,
				"tooltip": _bodypart_tooltip(b),
			}
		out.append(entry)
	return out


func _serialize_mutations(mutations: Array) -> Array:
	var out := []
	for m in mutations:
		if m != null:
			out.append(_mutation_option(m))
	return out


func _current_mutation_ids() -> Array:
	var out := []
	var p = G.player
	if is_instance_valid(p):
		for m in p.mutations:
			if m != null:
				out.append(_res_id(m))
	return out


func _new_mutation_ids(before: Array) -> Array:
	var remaining := before.duplicate()
	var added := []
	for id in _current_mutation_ids():
		var i := remaining.find(id)
		if i >= 0:
			remaining.remove_at(i)
		else:
			added.append(id)
	return added


# ------------------------------------------------------------------ choices


func _collect_choices() -> Array:
	var groups := []
	var by_group := {}
	for r in get_tree().get_nodes_in_group("bodypart_reward"):
		if not (r is BodypartReward) or not r.is_inside_tree() or _is_shop_item(r.get_parent()):
			continue
		var opt = _reward_option(r)
		if opt == null:
			continue
		var g := _choice_group(r)
		var cid := "reward:%s" % (g if g != "" else "single:%d" % r.get_instance_id())
		if not by_group.has(cid):
			by_group[cid] = {
				"choice_id": cid, "kind": "reward", "exclusive": g != "", "options": []
			}
			groups.append(by_group[cid])
		by_group[cid]["options"].append(opt)
		var iid := r.get_instance_id()
		if not _connected_rewards.has(iid) and r.has_signal("picked_up"):
			_connected_rewards[iid] = true
			r.picked_up.connect(_on_reward_picked.bind(cid, opt["key"]))

	var shop := _collect_shop()
	if not shop.is_empty():
		groups.append(shop)

	var editor = G.editor
	if (
		is_instance_valid(editor)
		and editor.has_method("is_choosing_mutation")
		and editor.is_choosing_mutation()
	):
		var options := []
		for m in editor.get("mutations"):
			if m != null:
				options.append(_mutation_option(m))
		var lvl = G.player.level if is_instance_valid(G.player) else 0
		(
			groups
			. append(
				{
					"choice_id": "level_up:%s:%s" % [str(G.rng_seed), lvl],
					"kind": "level_up",
					"exclusive": true,
					"options": options,
				}
			)
		)
	return groups


func _collect_shop() -> Dictionary:
	var room = G.current_room
	if not is_instance_valid(room):
		return {}
	var items := []
	_find_shop_items(room, items)
	if items.is_empty():
		return {}
	var options := []
	for n in items:
		var iid: int = n.get_instance_id()
		var was_unpaid := _shop_paid.get(iid, true) == false
		var paid: bool = n.get("paid") == true
		_shop_paid[iid] = paid
		var opt := _shop_option(n)
		if paid:
			if was_unpaid:
				_log_event(
					"choice_taken",
					{
						"choice_id": _shop_choice_id(room),
						"kind": "shop",
						"taken": opt["key"],
						"cost": opt.get("cost"),
						"pay_with_blood": opt.get("pay_with_blood"),
					}
				)
			continue
		options.append(opt)
	if options.is_empty():
		return {}
	return {
		"choice_id": _shop_choice_id(room), "kind": "shop", "exclusive": false, "options": options
	}


func _shop_choice_id(room) -> String:
	return "shop:%d:%d" % [room.get_instance_id(), G.level_number]


func _find_shop_items(node: Node, out: Array) -> void:
	for c in node.get_children():
		if _is_shop_item(c):
			out.append(c)
		else:
			_find_shop_items(c, out)


func _is_shop_item(node) -> bool:
	if node == null:
		return false
	var script = node.get_script()
	if script != null and str(script.resource_path).ends_with("shop_item.gd"):
		return true
	return node.has_method("clear_price") and node.get("pay_with_blood") != null


func _reward_option(r) -> Variant:
	if r.get("deleted") == true:
		return null
	var res = r.get("bodypart_resource")
	if res == null:
		return null
	if res is Mutation:
		return _mutation_option(res)
	var opt := {
		"type": "bodypart",
		"id": _res_id(res),
		"name": tr(res.ui_name),
		"description": tr(res.description) if res.get("description") else "",
		"tags": _tag_names(res.tags),
		"needs_connection":
		_tag_names(
			(
				res.get("needs_connection_warning")
				if res.get("needs_connection_warning") != null
				else []
			)
		),
	}
	var b = r.get("bodypart")
	if is_instance_valid(b):
		opt["rarity"] = _enum_name(Bodypart.Rarity, b.rarity)
		opt["tooltip"] = _bodypart_tooltip(b)
	else:
		opt["rarity_range"] = [
			_enum_name(Bodypart.Rarity, r.get("rarity_from")),
			_enum_name(Bodypart.Rarity, r.get("rarity_to")),
		]
	opt["key"] = "%s@%s" % [opt["id"], opt.get("rarity", "?")]
	return opt


func _shop_option(n) -> Dictionary:
	var opt := {}
	for c in n.get_children():
		if c is BodypartReward:
			var r = _reward_option(c)
			if r != null:
				opt = r
				break
		elif c is Pickup:
			var sc = c.get_script()
			var pid := (
				str(sc.resource_path).get_file().get_basename() if sc != null else str(c.name)
			)
			opt = {
				"type": "pickup",
				"id": pid,
				"name": pid.capitalize(),
				"is_health": c is HealthPickup,
				"key": pid
			}
			break
	if opt.is_empty():
		opt = {"type": "unknown", "id": str(n.name), "name": str(n.name), "key": str(n.name)}
	opt["cost"] = n.get("cost")
	opt["pay_with_blood"] = n.get("pay_with_blood") == true
	opt["key"] = "%s#%d" % [opt["key"], n.get_instance_id()]
	return opt


func _mutation_option(m) -> Dictionary:
	var id := _res_id(m)
	var opt := {
		"type": "evolution" if m is Evolution else "mutation",
		"id": id,
		"key": id,
		"name": tr(m.get("ui_name")) if m.get("ui_name") else id,
		"description": tr(m.get("description")) if m.get("description") else "",
		"tooltip": _mutation_tooltip(m, id),
	}
	if m is Evolution:
		opt["bonus_damage"] = m.get("bonus_damage")
		opt["bonus_hp"] = m.get("bonus_hp")
	return opt


func _bodypart_tooltip(b) -> String:
	var key := "b%d" % b.get_instance_id()
	if not _tooltip_cache.has(key):
		_tooltip_cache[key] = b.tooltip_text() if b.has_method("tooltip_text") else ""
	return _tooltip_cache[key]


func _mutation_tooltip(m, id: String) -> String:
	var key := "m" + id
	if not _tooltip_cache.has(key):
		_tooltip_cache[key] = m.tooltip_text() if m.has_method("tooltip_text") else ""
	return _tooltip_cache[key]


## Mutually-exclusive reward group for r: ancestor BodypartReward3Choice node,
## else the choose_one unique_from set, else the parent node. "" if independent.
func _choice_group(r) -> String:
	var anc := r.get_parent()
	while anc != null:
		var anc_script = anc.get_script()
		if (
			anc_script != null
			and str(anc_script.resource_path).ends_with("bodypart_reward_3_choice.gd")
		):
			return "choice3:%d" % anc.get_instance_id()
		anc = anc.get_parent()
	if r.get("choose_one") == true:
		var unique_from = r.get("unique_from")
		if unique_from is Array and not unique_from.is_empty():
			var ids := [r.get_instance_id()]
			for u in unique_from:
				if is_instance_valid(u):
					ids.append(u.get_instance_id())
			ids.sort()
			var parts := []
			for i in ids:
				parts.append(str(i))
			return "choose:" + ",".join(parts)
		var parent = r.get_parent()
		return "choose:%d" % parent.get_instance_id() if parent else ""
	return ""


# ------------------------------------------------------------------ catalog


func _try_dump_catalog() -> void:
	if G.bodyparts == null or G.bodyparts.is_empty():
		return
	_catalog_dumped = true
	var bodyparts := []
	for res in G.bodyparts:
		if res == null:
			continue
		(
			bodyparts
			. append(
				{
					"id": _res_id(res),
					"name_key": res.ui_name,
					"name": tr(res.ui_name),
					"description": tr(res.description) if res.get("description") else "",
					"tags": _tag_names(res.tags),
					"random_weight": res.random_weight,
					"disabled": res.disabled,
					"needs_connection_warning": _tag_names(res.needs_connection_warning),
				}
			)
		)
	var mutations := []
	for m in G.mutations:
		if m != null:
			var entry := _mutation_option(m)
			entry["kind"] = entry["type"]
			entry["random_weight"] = m.get("random_weight")
			entry["reward_drop_rate"] = m.get("reward_drop_rate")
			mutations.append(entry)
	var catalog := {
		"bodyparts": bodyparts, "mutations": mutations, "source": "live", "mod_version": MOD_VERSION
	}
	var f := FileAccess.open(CATALOG_PATH, FileAccess.WRITE)
	if f:
		f.store_string(JSON.stringify(catalog, "  "))
		f.close()
	_log_event("catalog", {"catalog": catalog})
	ModLoaderLog.info(
		"Wrote catalog (%d bodyparts, %d mutations)" % [bodyparts.size(), mutations.size()], LOG
	)


# ------------------------------------------------------------------ helpers


func _res_id(res) -> String:
	var path := str(res.resource_path)
	if path == "":
		var ui_name = res.get("ui_name")
		if ui_name:
			return str(ui_name)
		path = str(res.get_script().resource_path) if res.get_script() else ""
	return path.get_file().get_basename()


func _tag_names(tags) -> Array:
	var out := []
	for t in tags:
		out.append(_enum_name(G.BodypartTags, t))
	return out


func _enum_name(e, value) -> String:
	for k in e:
		if e[k] == value:
			return k
	return str(value)


func _parasite_name() -> String:
	return _enum_name(G.ParasiteType, G.selected_parasite)
