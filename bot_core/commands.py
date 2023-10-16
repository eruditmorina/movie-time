from datetime import datetime
import discord
import re
from managers.movie_night_manager import MovieNightManager
from bot_core.discord_events import DiscordEvents
from bot_core.discord_actions import create_header_embed, create_movie_embed
from bot_core.helpers import parse_start_time
from bot_core.helpers  import TimeZones, local_to_utc, datetime_to_unix, utc_to_local, round_to_next_quarter_hour

class MovieCommands:
    def __init__(self, movie_night_manager, movie_night_service, movie_event_manager, discord_token):
        self.movie_night_manager = movie_night_manager
        self.movie_night_service = movie_night_service
        self.movie_event_manager = movie_event_manager
        self.discord_events = DiscordEvents(discord_token)
        self.server_timezone = TimeZones.UTC
    
    def parse_movie_urls(self, movie_urls):
        if isinstance(movie_urls, str):
            return list(filter(None, re.split(r'[,\t\s]+', movie_urls)))
        elif isinstance(movie_urls, list):
            return movie_urls
        return []

    async def create_movie_night(self, interaction, title: str, description: str, server_timezone: TimeZones.UTC, start_time: str = None):
        if server_timezone is None:
            server_timezone = 'UTC'
        else:
            self.server_timezone = server_timezone
        if start_time:
            parsed_time = parse_start_time(start_time)
            parsed_time = local_to_utc(parsed_time, server_timezone)
        else:
            parsed_time = datetime.utcnow()
            
        rounded_time = round_to_next_quarter_hour(parsed_time)
        movie_night_id = self.movie_night_manager.create_movie_night(title, description, rounded_time) 
        await interaction.response.send_message(f"Movie Night created with ID: {movie_night_id}")

    async def remove_movie_event_command(self, interaction, movie_event_id=None):
        if movie_event_id is None:
            movie_event_id = self.movie_event_manager.find_last_movie_event()
                
        if movie_event_id is None:
            await interaction.response.send_message("No movie event found to remove.")
            return
            
        discord_event_id, result_message = self.movie_event_manager.remove_movie_event(movie_event_id)
            
        if discord_event_id: 
            await self.discord_events.delete_event(guild_id=interaction.guild.id,event_id=discord_event_id)
            
        await interaction.response.send_message(result_message)

    async def add_movies(self, interaction, movie_urls: str or list, movie_night_id: int = None):
        await interaction.response.defer()

        movie_urls = self.parse_movie_urls(movie_urls)
        if not movie_urls:
            await interaction.followup.send("No valid movie URLs provided.")
            return
        
        await self.process_movie_urls(interaction, movie_urls, movie_night_id)
    
    async def process_movie_urls(self, interaction, movie_urls: str or list, movie_night_id: int = None):
        if movie_night_id is None:
            movie_night_id = self.movie_night_manager.get_most_recent_movie_night_id()
            if movie_night_id is None:
                await interaction.followup.send("No movie nights found.")
                return
            
        for movie_url in movie_urls:
            movie_event_id = await self.movie_night_service.add_movie_to_movie_night(movie_night_id, movie_url)

            if not movie_event_id:
                await interaction.followup.send(f'Failed to add movie: "{movie_url}".')
                continue
            await interaction.followup.send(f'Added Movie "{movie_url}" to Movie Night. Movie Event ID is: {movie_event_id}')

    async def post_movie_night(self, interaction, movie_night_id: int = None): 
        await interaction.response.defer()
        if not movie_night_id:
            movie_night_id = self.movie_night_manager.get_most_recent_movie_night_id()
            if not movie_night_id:
                await interaction.followup.send("No recent Movie Night found.")
                return

        movie_night = self.movie_night_manager.get_movie_night(movie_night_id)
        if not movie_night:
            await interaction.followup.send(f"No Movie Night found with ID: {movie_night_id}")
            return

        all_embeds = []
        
        header_embed = create_header_embed(interaction, movie_night)
        all_embeds.append(header_embed)

        total_movies = len(movie_night.events)
        for index, movie_event in enumerate(movie_night.events):
            movie_embed = create_movie_embed(movie_event, index, total_movies)
            all_embeds.append(movie_embed)

        await interaction.followup.send(embeds=all_embeds)
    
    async def view_movie_night(self, interaction, movie_night_id: int = None):
        await interaction.response.defer()
        if movie_night_id is None:
            movie_night_id = self.movie_night_manager.get_most_recent_movie_night_id()
            if movie_night_id is None:
                await interaction.followup.send("No movie nights found.")
                return

        movie_night_details = self.movie_night_manager.get_movie_night_details(movie_night_id)

        if not movie_night_details:
            await interaction.followup.send("Movie Night not found.")
            return

        response_text = f"Movie Night #{movie_night_id}: {movie_night_details['title']}\n"
        response_text += f"Description: {movie_night_details['description']}\n"
        for event in movie_night_details['events']:
            start_time = utc_to_local(event['start_time'],self.server_timezone)
            start_time_unix = datetime_to_unix(start_time)
            response_text += f"  - Event ID: {event['event_id']}\n - Name: {event['movie_name']}\n - Start Time: <t:{start_time_unix}:F>\n\n"

        await interaction.followup.send(response_text)
        
    async def edit_movie_night(self, interaction, movie_night_id: int = None, title: str = None, description: str = None):
        if movie_night_id is None:
            movie_night_id = self.movie_night_manager.get_most_recent_movie_night_id()
            if movie_night_id is None:
                await interaction.followup.send("No movie nights found.")
                return

        if title or description is not None:
            movie_night_id = self.movie_night_manager.update_movie_night(movie_night_id, title, description) 
    
        await interaction.response.send_message(f"Movie Night updated on ID: {movie_night_id}")

    async def delete_event(self, interaction, event_id: int):
        await interaction.response.defer()

        success = self.movie_night_manager.delete_movie_event(event_id)

        if success:
            await interaction.followup.send(f"Successfully deleted Movie Event with ID: {event_id}")
        else:
            await interaction.followup.send("Failed to delete movie event.")

class ConfigCommands:
    def __init__(self, config_manager):
        self.config_manager = config_manager
    
    async def config(self, interaction, stream_channel: discord.VoiceChannel = None, announcement_channel: discord.TextChannel = None, ping_role: discord.Role = None,  timezone: TimeZones = None):
        response_messages = []
        config_dict = {}

        if not any([stream_channel, announcement_channel, ping_role, timezone]):
            await interaction.response.send_message("Use the config command to set up the movie bot. You can configure the stream channel, announcement channel, and ping role.")
            return
        
        if stream_channel:
            config_dict['stream_channel'] = stream_channel.id
            response_messages.append(f"Stream channel set to {stream_channel.mention}")

        if announcement_channel:
            config_dict['announcement_channel'] = announcement_channel.id
            response_messages.append(f"Announcement channel set to {announcement_channel.mention}")

        if ping_role:
            config_dict['ping_role'] = ping_role.id
            response_messages.append(f"Ping role set to **{ping_role.name}**")

        if timezone:
            config_dict['timezone'] = timezone.value
            response_messages.append(f"Time zone set to **{timezone.name}**")

        self.config_manager.save_settings(interaction.guild.id, config_dict)

        await interaction.response.defer()
        await interaction.followup.send("\n".join(response_messages))