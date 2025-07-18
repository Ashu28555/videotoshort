import streamlit as st
import os
import subprocess
import tempfile
import shutil
from pathlib import Path
import time
import zipfile
import io

# Page configuration
st.set_page_config(
    page_title="Video Splitter Pro",
    page_icon="🎬",
    layout="wide",
    initial_sidebar_state="expanded"
)

class VideoSplitterApp:
    def __init__(self):
        self.temp_dir = tempfile.mkdtemp()
        self.output_dir = os.path.join(self.temp_dir, "output_videos")
        Path(self.output_dir).mkdir(exist_ok=True)
        
    def check_dependencies(self):
        """Check if required tools are installed"""
        missing_deps = []
        
        if not shutil.which("ffmpeg"):
            missing_deps.append("FFmpeg")
        if not shutil.which("yt-dlp"):
            missing_deps.append("yt-dlp")
            
        return missing_deps
    
    def download_video(self, url, progress_placeholder):
        """Download video from URL using yt-dlp"""
        try:
            output_path = os.path.join(self.temp_dir, "downloaded_video.%(ext)s")
            
            with progress_placeholder.container():
                st.info("📥 Downloading video...")
                progress_bar = st.progress(0)
                
            command = [
                "yt-dlp",
                "--format", "best[ext=mp4]/best",
                "--output", output_path,
                url
            ]
            
            result = subprocess.run(command, capture_output=True, text=True, check=False)
            
            if result.returncode == 0:
                downloaded_file = self.find_downloaded_file(output_path)
                if downloaded_file:
                    with progress_placeholder.container():
                        st.success("✅ Video downloaded successfully!")
                        progress_bar.progress(100)
                    return downloaded_file
            
            with progress_placeholder.container():
                st.error(f"❌ Download failed: {result.stderr}")
            return None
            
        except Exception as e:
            with progress_placeholder.container():
                st.error(f"❌ Exception during download: {e}")
            return None
    
    def find_downloaded_file(self, pattern):
        """Find the downloaded file"""
        base_name = pattern.split('.')[0]
        extensions = ['.mp4', '.webm', '.mkv', '.avi', '.mov']
        
        for ext in extensions:
            potential_file = base_name + ext
            if os.path.exists(potential_file):
                return potential_file
        
        # Look for recently created video files
        video_files = []
        for ext in extensions:
            video_files.extend(Path(self.temp_dir).glob(f'*{ext}'))
        
        if video_files:
            return str(max(video_files, key=os.path.getctime))
        
        return None
    
    def get_video_info(self, video_path):
        """Get video duration and dimensions"""
        try:
            # Get duration
            duration_cmd = [
                "ffprobe", "-v", "quiet", "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1", video_path
            ]
            duration_result = subprocess.run(duration_cmd, capture_output=True, text=True)
            duration = float(duration_result.stdout.strip()) if duration_result.returncode == 0 else None
            
            # Get dimensions
            dimensions_cmd = [
                "ffprobe", "-v", "quiet", "-show_entries", "stream=width,height",
                "-of", "csv=p=0", "-select_streams", "v:0", video_path
            ]
            dimensions_result = subprocess.run(dimensions_cmd, capture_output=True, text=True)
            
            if dimensions_result.returncode == 0:
                width, height = dimensions_result.stdout.strip().split(',')
                dimensions = (int(width), int(height))
            else:
                dimensions = None
                
            return duration, dimensions
            
        except Exception as e:
            st.error(f"Error getting video info: {e}")
            return None, None
    
    def parse_time_input(self, time_str):
        """Parse time input in various formats"""
        time_str = time_str.strip()
        
        if ':' in time_str:
            parts = time_str.split(':')
            if len(parts) == 2:  # MM:SS
                minutes, seconds = parts
                return int(minutes) * 60 + float(seconds)
            elif len(parts) == 3:  # HH:MM:SS
                hours, minutes, seconds = parts
                return int(hours) * 3600 + int(minutes) * 60 + float(seconds)
        else:
            return float(time_str)
    
    def seconds_to_time(self, seconds):
        """Convert seconds to MM:SS format"""
        minutes = int(seconds // 60)
        secs = seconds % 60
        return f"{minutes}:{secs:05.2f}"
    
    def parse_aspect_ratio(self, ratio_str):
        """Parse aspect ratio string"""
        if ratio_str.lower() == 'original':
            return None
        
        if ':' not in ratio_str:
            raise ValueError("Invalid format")
        
        width, height = ratio_str.split(':')
        return (float(width), float(height))
    
    def calculate_crop_dimensions(self, original_width, original_height, target_ratio):
        """Calculate crop dimensions for aspect ratio"""
        if target_ratio is None:
            return None
        
        target_width, target_height = target_ratio
        target_aspect = target_width / target_height
        original_aspect = original_width / original_height
        
        if abs(target_aspect - original_aspect) < 0.01:
            return None
        
        if target_aspect > original_aspect:
            new_height = int(original_width / target_aspect)
            new_width = original_width
            crop_x = 0
            crop_y = (original_height - new_height) // 2
        else:
            new_width = int(original_height * target_aspect)
            new_height = original_height
            crop_x = (original_width - new_width) // 2
            crop_y = 0
        
        # Ensure even dimensions
        new_width = new_width - (new_width % 2)
        new_height = new_height - (new_height % 2)
        crop_x = crop_x - (crop_x % 2)
        crop_y = crop_y - (crop_y % 2)
        
        return {
            'width': new_width, 'height': new_height,
            'x': crop_x, 'y': crop_y
        }
    
    def process_segment(self, input_path, segment_info, index):
        """Process a single video segment"""
        output_path = os.path.join(self.output_dir, f"video_part_{index:02d}.mp4")
        
        try:
            # Get original dimensions if aspect ratio is specified
            if segment_info['aspect_ratio']:
                duration, dimensions = self.get_video_info(input_path)
                if not dimensions:
                    return False, "Could not get video dimensions"
                
                crop_info = self.calculate_crop_dimensions(
                    dimensions[0], dimensions[1], segment_info['aspect_ratio']
                )
            else:
                crop_info = None
            
            command = [
                "ffmpeg", "-i", input_path,
                "-ss", str(segment_info['start']),
                "-t", str(segment_info['duration']),
            ]
            
            if crop_info:
                crop_filter = f"crop={crop_info['width']}:{crop_info['height']}:{crop_info['x']}:{crop_info['y']}"
                command.extend(["-vf", crop_filter])
            
            command.extend([
                "-c:v", "libx264", "-c:a", "aac",
                "-avoid_negative_ts", "make_zero", "-y", output_path
            ])
            
            result = subprocess.run(command, capture_output=True, text=True, timeout=120)
            
            if result.returncode == 0 and os.path.exists(output_path):
                return True, output_path
            else:
                return False, f"FFmpeg error: {result.stderr}"
                
        except Exception as e:
            return False, f"Exception: {e}"
    
    def create_zip_file(self):
        """Create a zip file of all output videos"""
        zip_buffer = io.BytesIO()
        
        with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
            for filename in os.listdir(self.output_dir):
                if filename.endswith('.mp4'):
                    file_path = os.path.join(self.output_dir, filename)
                    zip_file.write(file_path, filename)
        
        zip_buffer.seek(0)
        return zip_buffer.getvalue()

def main():
    st.title("🎬 Video Splitter Pro")
    st.markdown("**Split YouTube videos into custom segments with different aspect ratios**")
    
    # Initialize the app
    if 'app' not in st.session_state:
        st.session_state.app = VideoSplitterApp()
    
    app = st.session_state.app
    
    # Check dependencies
    missing_deps = app.check_dependencies()
    if missing_deps:
        st.error(f"❌ Missing dependencies: {', '.join(missing_deps)}")
        st.markdown("""
        **Installation Instructions:**
        - **FFmpeg**: Download from https://ffmpeg.org/download.html
        - **yt-dlp**: Install with `pip install yt-dlp`
        """)
        return
    
    # Sidebar for input
    with st.sidebar:
        st.header("📝 Input Settings")
        
        # URL input
        url = st.text_input("🔗 YouTube URL", placeholder="https://www.youtube.com/watch?v=...")
        
        # Number of segments
        num_segments = st.number_input("📊 Number of segments", min_value=1, max_value=10, value=1)
        
        # Download button
        if st.button("📥 Download & Analyze Video", type="primary"):
            if url:
                st.session_state.video_path = None
                st.session_state.video_info = None
                
                progress_placeholder = st.empty()
                downloaded_file = app.download_video(url, progress_placeholder)
                
                if downloaded_file:
                    st.session_state.video_path = downloaded_file
                    duration, dimensions = app.get_video_info(downloaded_file)
                    st.session_state.video_info = {
                        'duration': duration,
                        'dimensions': dimensions
                    }
                    st.rerun()
            else:
                st.error("Please enter a YouTube URL")
    
    # Main content area
    if 'video_path' in st.session_state and st.session_state.video_path:
        video_info = st.session_state.video_info
        
        # Display video info
        col1, col2 = st.columns(2)
        with col1:
            st.metric("⏱️ Duration", app.seconds_to_time(video_info['duration']))
        with col2:
            if video_info['dimensions']:
                w, h = video_info['dimensions']
                st.metric("📐 Resolution", f"{w}x{h}")
        
        st.markdown("---")
        
        # Segment configuration
        st.header("⚙️ Configure Segments")
        
        segments = []
        
        for i in range(num_segments):
            st.subheader(f"🎬 Segment {i+1}")
            
            col1, col2, col3 = st.columns(3)
            
            with col1:
                start_time = st.text_input(
                    f"Start time", 
                    key=f"start_{i}",
                    placeholder="0 or 0:30",
                    help="Format: seconds (30) or MM:SS (1:30)"
                )
            
            with col2:
                end_time = st.text_input(
                    f"End time", 
                    key=f"end_{i}",
                    placeholder="30 or 2:00",
                    help="Format: seconds (30) or MM:SS (1:30)"
                )
            
            with col3:
                aspect_ratio = st.selectbox(
                    f"Aspect ratio",
                    options=["original", "16:9", "1:1", "3:4", "9:16"],
                    key=f"ratio_{i}",
                    help="Choose aspect ratio for this segment"
                )
            
            # Validate and store segment info
            if start_time and end_time:
                try:
                    start_seconds = app.parse_time_input(start_time)
                    end_seconds = app.parse_time_input(end_time)
                    
                    if start_seconds >= end_seconds:
                        st.error(f"❌ Start time must be less than end time for segment {i+1}")
                        continue
                    
                    if start_seconds >= video_info['duration']:
                        st.error(f"❌ Start time exceeds video duration for segment {i+1}")
                        continue
                    
                    if end_seconds > video_info['duration']:
                        st.warning(f"⚠️ End time exceeds video duration for segment {i+1}, will be adjusted")
                        end_seconds = video_info['duration']
                    
                    duration = end_seconds - start_seconds
                    parsed_ratio = app.parse_aspect_ratio(aspect_ratio)
                    
                    segments.append({
                        'start': start_seconds,
                        'end': end_seconds,
                        'duration': duration,
                        'aspect_ratio': parsed_ratio,
                        'ratio_text': aspect_ratio
                    })
                    
                    st.success(f"✅ Segment {i+1}: {start_seconds:.1f}s to {end_seconds:.1f}s ({duration:.1f}s) - {aspect_ratio}")
                    
                except ValueError as e:
                    st.error(f"❌ Invalid time format for segment {i+1}: {e}")
        
        st.markdown("---")
        
        # Process segments
        if segments and st.button("🎯 Process All Segments", type="primary"):
            progress_bar = st.progress(0)
            status_text = st.empty()
            
            successful_segments = []
            failed_segments = []
            
            for i, segment in enumerate(segments):
                status_text.text(f"Processing segment {i+1}/{len(segments)}...")
                
                success, result = app.process_segment(st.session_state.video_path, segment, i+1)
                
                if success:
                    successful_segments.append(result)
                    st.success(f"✅ Segment {i+1} completed successfully")
                else:
                    failed_segments.append(f"Segment {i+1}: {result}")
                    st.error(f"❌ Segment {i+1} failed: {result}")
                
                progress_bar.progress((i + 1) / len(segments))
            
            status_text.text("Processing complete!")
            
            # Show results
            st.markdown("---")
            st.header("📊 Results")
            
            col1, col2 = st.columns(2)
            with col1:
                st.metric("✅ Successful", len(successful_segments))
            with col2:
                st.metric("❌ Failed", len(failed_segments))
            
            # Download section
            if successful_segments:
                st.markdown("### 📥 Download Results")
                
                # Create zip file
                zip_data = app.create_zip_file()
                
                st.download_button(
                    label="📦 Download All Videos (ZIP)",
                    data=zip_data,
                    file_name="video_segments.zip",
                    mime="application/zip"
                )
                
                # Individual file downloads
                with st.expander("📁 Individual Downloads"):
                    for i, file_path in enumerate(successful_segments):
                        filename = os.path.basename(file_path)
                        with open(file_path, 'rb') as f:
                            st.download_button(
                                label=f"📹 {filename}",
                                data=f.read(),
                                file_name=filename,
                                mime="video/mp4",
                                key=f"download_{i}"
                            )
            
            if failed_segments:
                with st.expander("❌ Failed Segments"):
                    for error in failed_segments:
                        st.error(error)
    
    else:
        # Welcome message
        st.info("👆 Enter a YouTube URL in the sidebar to get started!")
        
        # Instructions
        st.markdown("""
        ### 🚀 How to Use:
        
        1. **Enter YouTube URL** in the sidebar
        2. **Set number of segments** you want to create
        3. **Download & analyze** the video
        4. **Configure each segment** with:
           - Start time (seconds or MM:SS format)
           - End time (seconds or MM:SS format)
           - Aspect ratio (16:9, 1:1, 3:4, 9:16, or original)
        5. **Process segments** and download results!
        
        ### 🎯 Perfect for:
        - Creating social media content
        - Extracting video highlights
        - Converting aspect ratios for different platforms
        - Batch processing multiple segments
        """)

if __name__ == "__main__":
    main()
