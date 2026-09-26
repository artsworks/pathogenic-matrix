extends Node

const MOD_DIR := "Artsworks-PathogenicMatrix"
const LOG_NAME := "Artsworks-PathogenicMatrix:Main"

var mod_dir_path := ""
var observer: Node


func _init() -> void:
	mod_dir_path = ModLoaderMod.get_unpacked_dir().path_join(MOD_DIR)


func _ready() -> void:
	ModLoaderLog.info("Ready", LOG_NAME)
	var observer_script = load(mod_dir_path.path_join("observer.gd"))
	observer = observer_script.new()
	observer.name = "PathogenicMatrixObserver"
	get_tree().root.add_child.call_deferred(observer)
