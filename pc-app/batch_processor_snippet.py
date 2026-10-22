    def _process_message_buffer(self):
        """Process buffered messages in batch (called every 100ms by QTimer)"""
        if not self.stream_message_buffer:
            return
        
        # Get all messages from buffer atomically
        with self.buffer_lock:
            messages = self.stream_message_buffer[:]
            self.stream_message_buffer.clear()
        
        # Process in batch - much faster than individual emit()
        # Only show last 10 messages to prevent UI flooding
        for message, color in messages[-10:]:
            self.traffic_message.emit(message, color)
