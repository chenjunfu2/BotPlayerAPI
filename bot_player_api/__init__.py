from mcdreforged.api.all import *
from typing import Set
from typing import List
from parse import parse
import threading
import re

PLUGIN_METADATA = ServerInterface.get_instance().as_plugin_server_interface().get_self_metadata()
set_lock = threading.Lock()
online_players = set()

class Config(Serializable):
	suffix: str = '@bot'#后缀
config = Config()

def on_load(server, old):
	global online_players
	global config

	if old is not None and hasattr(old, 'online_players'):#继承之前的数据
		online_players = old.online_players
	config = server.load_config_simple(target_class = Config)#配置重新加载
	
	#如果可以，使用data api获取一次当前服务器玩家集合，比对数据，存在插件重载过程玩家变动、或插件被卸载后第一次加载的情况
	#本着宁可错判bot不可错判玩家的原则，bot当玩家没多大副作用，但是玩家当bot有可能导致pb跳过备份而出问题
	#所以使用服务器玩家集合进行一次同步，避免数据错误
	if server.is_server_startup():#服务器已开启状态才执行
		update_player_list(server)

	server.register_help_message('!!list', '获取玩家集合')
	server.register_help_message('!!updt', '更新玩家集合')
	server.register_command(Literal('!!list').runs(output_list))
	server.register_command(Literal('!!updt').runs(cmd_update_player_list))
	

def cmd_update_player_list(source: CommandSource, context: dict):
	update_player_list(source.get_server())
	source.get_server().logger.info('updating...')
	source.reply('updating...')

@new_thread(PLUGIN_METADATA.name + 'update_player_list')
def update_player_list(server,timeout:float=5):
	global online_players
	global set_lock
	global config
	api = server.get_plugin_instance('minecraft_data_api')
	if api is not None:
		server_player_list: List[str] = []
		try:
			result = api.get_server_player_list(timeout = timeout)
			if result is not None:
				server_player_list = list(map(str, result[2]))
		except Exception as e:
			server.logger.exception('Queried players from minecraft_data_api error', e)
			return

		if result is None:
			server.logger.warning('Queried players from minecraft_data_api failed')
			return
		
		with set_lock:
			if online_players:#如果为空（插件刚启动的情况）跳过检测，直接设置成服务器玩家集合
				#获取所有bot的名称
				bot_set = set([s.removesuffix(config.suffix) for s in online_players if s.endswith(config.suffix)])
				#检测所有bot名字是否存在于server_player_list中，有的给加上后缀，并以服务器玩家集合为准
				for i in range(len(server_player_list)):
					if server_player_list[i] in bot_set:
						server_player_list[i] += config.suffix
			#替换集合
			online_players = set(server_player_list)
	server.logger.info('update ok')

def on_server_stop(server, return_code):
	global online_players
	global set_lock
	with set_lock:
		online_players = set()

def player_joined(server, player, ip):
	global online_players
	global set_lock
	server.logger.info(player + ' [' + ip + '] join')

	with set_lock:
		if ip == 'local':#is_bot
			if bot_name(player) in online_players:#是bot且有bot后缀，跳过
				return
			elif player in online_players:#是bot但是没后缀，添加后缀
				online_players.remove(player)
				online_players.add(bot_name(player))
			else:#不在集合中
				online_players.add(bot_name(player))
		else:
			if player in online_players:#是玩家且无后缀，跳过
				return
			elif bot_name(player) in online_players:#是玩家但是有bot后缀，删除后缀
				online_players.remove(bot_name(player))
				online_players.add(player)
			else:#不在集合中
				online_players.add(player)

def player_left(server, player):
	global online_players
	global set_lock
	server.logger.info(player + ' left')

	with set_lock:
		if player in online_players:#判断是不是玩家
			online_players.remove(player)
		elif bot_name(player) in online_players:#再判断是不是bot
			online_players.remove(bot_name(player))

def on_info(server: PluginServerInterface, info: Info) -> None:
	if info.is_from_server:
		if (m := re.compile(r'(?P<name>[^\[]+)\[(?P<ip>.*?)\] logged in with entity id \d+ at \(.+\)').fullmatch(info.content)) is not None:
			player_joined(server, m['name'], m['ip'])
		if (m := re.compile(r'(?P<name>[^ ]+) left the game').fullmatch(info.content)) is not None:
			player_left(server, m['name'])
		
def bot_name(player: str):
	global config
	return player + config.suffix#拼接后缀

def get_player_list() -> List[str]:
	"""Get all online player list"""
	global online_players
	global set_lock
	with set_lock:
		return list(online_players)#转换会进行拷贝，无需copy

@new_thread(PLUGIN_METADATA.name + 'output_list')
def output_list(source: CommandSource, context: dict):
	opt = '[' + ', '.join(get_player_list()) + ']'
	source.reply(opt)