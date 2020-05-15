import discord
from editdistance import eval as levdist
from colour import Color
import sqlite3
import sys
import datetime
import random

client = discord.Client()
db = sqlite3.connect('data.db')

class dbinfo():
    tables = {
        # 'color': [
        #     'value INT PRIMARY KEY',
        #     'likes INT NOT NULL DEFAULT 0'
        # ],
        # 'liked_color': [
        #     'value INT NOT NULL',
        #     'user_id INT NOT NULL',
        #     'FOREIGN KEY(value) REFERENCES color(value)'
        # ],
        # 'saved_color': [
        #     'value INT NOT NULL',
        #     'user_id INT NOT NULL',
        #     'FOREIGN KEY(value) REFERENCES color(value)'
        # ],
        'previous_color': [
            'user_id INT PRIMARY KEY',
            'value INT NOT NULL',
            'FOREIGN KEY(value) REFERENCES color(value)'
        ]
    }

if 'init' in sys.argv:
    c = db.cursor()
    c.execute("SELECT name FROM sqlite_master WHERE type='table'")
    rows = c.fetchall()
    if rows:
        for key, val in dbinfo.tables.items():
            exists = False
            for r in rows:
                if r[0] == key:
                    exists = True
                    while True:
                        opt = input(f'Table {key} already exists, drop table and recreate? (y/n) ')
                        if opt[0] == 'y':
                            c.execute('DROP TABLE %s' % key)
                            c.execute(f'CREATE TABLE {key} ({",".join(val)})')
                            print('Recreated table %s' % key)
                            break
                        elif opt[0] == 'n':
                            quit()
                        else:
                            print('Unknown option %s' % opt)
            if not exists:
                c.execute(f'CREATE TABLE {key} ({",".join(val)})')
    else:
        for key, val in dbinfo.tables.items():
            c.execute(f'CREATE TABLE {key} ({",".join(val)})')
    db.commit()

def random_color():
    return Color(rgb=(
        random.randrange(0, 255) / 255.0,
        random.randrange(0, 255) / 255.0,
        random.randrange(0, 255) / 255.0
    ))

def lerp(a, b, t):
    return (b * t) + a * (1.0 - t)

def color_to_int(c: Color):
    return int(c.hex_l[1:], 16)

def color_from_int(n: int):
    return Color('#' + hex(n)[2:])

def insert_color(value):
    if isinstance(value, Color):
        value = color_to_int(value)
    if not isinstance(value, int):
        raise TypeError
    c = db.cursor()
    try:
        c.execute('INSERT INTO color (value) VALUES (?)', (value,))
    except sqlite3.IntegrityError:
        return False
    db.commit()
    return True

def fetch_color(value):
    if isinstance(value, Color):
        value = color_to_int(value)
    if not isinstance(value, int):
        raise TypeError
    c = db.cursor()
    c.execute('SELECT value, likes FROM color WHERE value=?', (value,))
    r = c.fetchone()
    return {
        'value': r[0],
        'likes': r[1]
    }

def like_color(value, user_id:int):
    if isinstance(value, Color):
        value = color_to_int(value)
    if not isinstance(value, int):
        raise TypeError
    c = db.cursor()
    c.execute('SELECT COUNT(*) FROM liked_color WHERE user_id=?', (user_id,))
    r = c.fetchone()
    if r and r[0] > 0:
        return False
    else:
        c.execute('INSERT INTO liked_color (value, user_id) VALUES (?, ?)', (value, user_id,))
        c.execute('SELECT COUNT(*) FROM liked_color WHERE value=?', (value,))
        r = c.fetchone()
        count = r[0] if r else 0
        c.execute('UPDATE color SET likes=? WHERE value=?', (count, value,))
    db.commit()
    return True

def save_previous_color(value, user_id:int):
    if isinstance(value, Color):
        value = color_to_int(value)
    if not isinstance(value, int):
        raise TypeError
    c = db.cursor()
    try:
        c.execute('INSERT INTO previous_color (user_id, value) VALUES (?, ?)', (user_id, value,))
    except sqlite3.IntegrityError:
        c.execute('UPDATE previous_color SET value=? WHERE user_id=?', (value, user_id,))
    db.commit()
    return True

def fetch_previous_color(user_id:int):
    c = db.cursor()
    c.execute('SELECT value FROM previous_color WHERE user_id=?', (user_id,))
    r = c.fetchone()
    if r:
        return color_from_int(r[0])
    else:
        return None

def get_member_color_role(member: discord.Member):
    for role in member.roles[::-1]:
        if role.name[0] == '#':
            return role
    return None

async def get_or_create_color_role(guild: discord.Guild, color):
    if not isinstance(color, Color):
        color = Color(color)
    color_role = None
    self_role_index = 0
    roles = await guild.fetch_roles()
    for role in roles:
        if role.name[0] == '#':
            if role.name == color.hex_l.upper():
                color_role = role
        elif role.name == 'Color Palette':
            self_role_position = role.position
    if color_role != None:
        return color_role
    try:
        color_role = await guild.create_role(name=color.hex_l.upper(), colour=discord.Colour(color_to_int(color)))
        await color_role.edit(position=self_role_position - 1)
        return color_role
    except discord.Forbidden:
        print("Error: The bot doesn't have permission to make roles.")
    return None

async def prune_unused_color_roles(guild: discord.Guild):
    roles = await guild.fetch_roles()
    for role in roles:
        if role.name[0] != '#':
            continue
        if not role.members:
            print('Deleting unused color role %s' % role.name)
            await role.delete()

async def set_member_color_role(member: discord.Member, color):
    current_role = get_member_color_role(member)
    if current_role:
        if current_role.colour.value == color_to_int(color):
            return True
        save_previous_color(current_role.colour.value, member.id)
        if len(current_role.members) == 1:
            await current_role.delete()
        else:
            await member.remove_roles(current_role)
    role = await get_or_create_color_role(member.guild, color)
    if not role:
        return False
    try:
        await member.add_roles(role)
    except discord.Forbidden:
        return False
    return True

class Context():
    def __init__(self, channel: discord.TextChannel, color):
        self.channel = channel
        if not isinstance(color, Color):
            color = Color(color)
        self.color = color
        self.datetime = datetime.datetime.now()
    def isold(self):
        return (self.datetime - datetime.datetime.now() > datetime.timedelta(minutes=15))

contexts = []

def push_context(channel: discord.TextChannel, color):
    global contexts
    contexts = [ c for c in contexts if not c.isold() and c.channel != channel ]
    contexts.append(Context(channel, color))

def get_context(channel: discord.TextChannel):
    global contexts
    for c in contexts:
        if c.channel == channel:
            if not c.isold():
                return c.color
            else:
                return None
    return None

async def send_color(channel: discord.TextChannel, color, message=None, push_color_context=True):
    if not isinstance(color, Color):
        color = Color(color)
    embed = discord.Embed(title=color.hex_l.upper(), description=f'*{message}*' if message else None, colour=color_to_int(color))
    try:
        await channel.send(embed=embed)
    except:
        return False
    if push_color_context:
        push_context(channel, color)
    return True

def clamp(n, min_n, max_n):
    return max(min_n, min(max_n, n))

def byte_comp_to_int(comp):
    try:
        comp = int(comp)
    except:
        return None
    return clamp(comp, 0, 255)

color_argument_docs = '''
    <color> can be a common name, such as 'red' or 'blue'.\n
    <color> can be a hex value, denoted by a pound sign follow by 3 or 6 base 16 components.\n
    Example: #fff is white, #000 is black, #f00 is red.
'''

commands_docs = {
    'use': ('use <color>', 'Set your name\'s color.\n' + color_argument_docs + '\nIf <color> is not given, the color displayed in the last 15 minutes is used. Otherwise, white is used.',),
    'revert': ('revert', 'Reverts your color back to the last one used.'),
    'show': ('show <color>', 'Shows the given color.\n' + color_argument_docs + '\nIf <color> is not given, a random color is shown.'),
    'random': ('random', 'Shows a random color.',),
    'rgb': ('rgb <red> <green> <blue>', '''
        Shows a color with the give RGB components.\n
        <red>, <green> and <blue> are integer values ranging from 0 to 255.
    ''',),
    'hsl': ('hsl <hue> <saturation> <luminance>', '''
        Shows a color with the give HSL components.\n
        <hue>, <saturation> and <luminance> are decimal values ranging from 0 to 1.
    ''',),
}

@client.event
async def on_ready():
    print(f'Logged into discord as {client.user}')

@client.event
async def on_message(message):
    global commands_docs

    if message.author == client.user:
        return
    
    if message.content[0] == '#':
        if message.content[1] == '#':
            args = message.content[2:].split(' ')
            if args[0] == 'use':
                if len(args) > 1:
                    color = Color(args[1])
                else:
                    color = get_context(message.channel)
                if not color:
                    color = Color('#fff')
                if await set_member_color_role(message.author, color):
                    await send_color(message.channel, color, 'Changed your color.')
                else:
                    await message.channel.send('Failed to change your color.')
            elif args[0] == 'like':
                pass
            elif args[0] == 'revert':
                color = fetch_previous_color(message.author.id)
                if color:
                    if await set_member_color_role(message.author, color):
                        await send_color(message.channel, color, 'Changed your color.')
                    else:
                        await message.channel.send('Failed to change your color.')
                else:
                    await message.channel.send('No previous color to revert to.')
            elif args[0] in [ 'color', 'show' ]:
                color = random_color()
                if len(args) > 1:
                    color = Color(args[1])
                await send_color(message.channel, color)
            elif args[0] == 'rgb':
                if len(args) != 4:
                    await message.channel.send('Please provide all three RGB components.\nExample: `##rgb 255 0 0` will show the color red.')
                else:
                    comps = (
                        byte_comp_to_int(args[1]) / 255.0,
                        byte_comp_to_int(args[2]) / 255.0,
                        byte_comp_to_int(args[3]) / 255.0
                    )
                    if None in comps:
                        await message.channel.send('Each RGB component must be an integer value between 0 and 255.')
                    else:
                        color = Color(rgb=comps)
                        await send_color(message.channel, color)
            elif args[0] == 'hsl':
                if len(args) != 4:
                    await message.channel.send('Please provide all three HSL components.\nExample: `##hsl 0 1 0.5` will show the color red.')
                else:
                    comps = (0, 0, 0)
                    try:
                        comps = (
                            float(args[1]),
                            float(args[2]),
                            float(args[3])
                        )
                    except ValueError:
                        await message.channel.send('Each HSL component must be an decimal value between 0 and 1.')
                    else:
                        color = Color(hsl=comps)
                        await send_color(message.channel, color)
            elif args[0] == 'setuphelp':
                await message.channel.send('''
                1. Make sure the bot has permission to manage roles.
                2. The bot generates color roles below its own role, so make sure its role is high enough in the list. Recommended to be higher than your member role.
                3. Make sure any roles above the color roles don't override the color. If a role's color is set to 'Default' then it 'falls through' to the next role in the list.
                ''')
            elif args[0] == 'random':
                await send_color(message.channel, random_color())
            elif args[0] in [ 'help', 'h', '?' ]:
                if len(args) > 1:
                    doc = commands_docs.get(args[1])
                    if not doc:
                        await message.channel.send(f'No documentation for command "{args[1]}".')
                    else:
                        await message.channel.send(embed=discord.Embed(title=f'##{doc[0]}', description=doc[1], colour=color_to_int(random_color())))
                else:
                    await message.channel.send(embed=discord.Embed(
                        title='Color Palette Commands',
                        description='''
                        **#<hex value>**  ─  *Equivalent to `##show #<hex value>`.*\n
                        **##setuphelp**  ─  *Bot not working? Run this command for some help.*\n
                        **##help <command>**  ─  *Shows more detailed docs for a specific command.*\n
                        **##use <color>**  ─  *Change your name's color to <color>.*\n
                        **##revert**  ─  *Revert to your previously used color.*\n
                        **##random**  ─  *Show a random color.*\n
                        **##show <color>**  ─  *Display <color>.*\n
                        **##rgb <red> <green> <blue>**  ─  *Display a color from RGB components.*\n
                        **##hsl <hue> <saturation> <luminance>**  ─  *Display a color from HSL components.*
                        ''',
                        colour=color_to_int(random_color())
                    ))
        else:
            send_color(message.channel, Color(message.content))

token = None
try:
    with open('token.txt') as file:
        token = file.read()
except:
    print('Failed to open file token.txt')
    quit()

client.run(token)
db.close()