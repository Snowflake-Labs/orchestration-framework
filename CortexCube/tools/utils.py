def parse_log_message(log_message):
    # Split the log message to extract the relevant part
    parts = log_message.split(' - ')
    if len(parts) >= 4:
        task_info = parts[3]
        # Check if the log message contains 'running' and 'task'
        if 'running' in task_info and 'task' in task_info:
            start = task_info.find('running') + len('running')
            end = task_info.find('task')
            tool_name = task_info[start:end].strip().replace('_', ' ').upper()
            
            # Determine tool type
            if 'CORTEXANALYST' in tool_name:
                tool_type = "Cortex Analyst"
                tool_name = tool_name.replace('CORTEXANALYST', "")
            elif 'CORTEXSEARCH' in tool_name:
                tool_type = "Cortex Search"
                tool_name = tool_name.replace('CORTEXSEARCH', "")
            else:
                tool_type = "Python"
                
            return f"Running {tool_name} {tool_type} Tool..."
