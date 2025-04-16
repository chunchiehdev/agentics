import React, { useState, useRef, useEffect } from 'react';
import axios from 'axios';

interface Message {
  role: 'user' | 'assistant';
  content: string;
  screenshot?: string;
  isTyping?: boolean;
}

interface SensitiveField {
  key: string;
  value: string;
}

const Chat: React.FC = () => {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [includeScreenshot, setIncludeScreenshot] = useState(true);
  const [displayedText, setDisplayedText] = useState('');
  const [currentTypingIndex, setCurrentTypingIndex] = useState(-1);
  const [sensitiveData, setSensitiveData] = useState<SensitiveField[]>([]);
  const [showSensitiveFields, setShowSensitiveFields] = useState(false);
  
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const chatWrapperRef = useRef<HTMLDivElement>(null);
  const typingSpeed = 10;

  
  useEffect(() => {
    const chatWrapper = chatWrapperRef.current;
    const appElement = document.querySelector('.App');
    const headerElement = document.querySelector('.App-header');
    
    if (chatWrapper && appElement && headerElement) {
      const updateScrollbar = () => {
        const { scrollTop, scrollHeight, clientHeight } = chatWrapper;
        const scrollPercentage = scrollTop / (scrollHeight - clientHeight);
        
        const headerHeight = (headerElement as HTMLElement).offsetHeight;
        

        if (scrollHeight > clientHeight) {
          appElement.classList.add('scrolling');
          

          const thumbHeight = Math.max(30, (clientHeight / scrollHeight) * clientHeight);

          const thumbTop = headerHeight + scrollPercentage * (clientHeight - thumbHeight);
          
          const pseudoStyle = document.createElement('style');
          pseudoStyle.id = 'scrollbar-style';
          
          const oldStyle = document.getElementById('scrollbar-style');
          if (oldStyle) {
            oldStyle.remove();
          }
          
          pseudoStyle.textContent = `
            .App::after {
              height: ${thumbHeight}px;
              top: ${thumbTop}px;
              opacity: ${scrollTop > 0 ? 1 : 0.7};
            }
          `;
          
          document.head.appendChild(pseudoStyle);
        } else {
          appElement.classList.remove('scrolling');
        }
      };
      
      chatWrapper.addEventListener('scroll', updateScrollbar);
      window.addEventListener('resize', updateScrollbar);
      
      updateScrollbar();
      
      return () => {
        chatWrapper.removeEventListener('scroll', updateScrollbar);
        window.removeEventListener('resize', updateScrollbar);
        const oldStyle = document.getElementById('scrollbar-style');
        if (oldStyle) {
          oldStyle.remove();
        }
      };
    }
  }, [messages]); 
  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  useEffect(() => {
    const typingMessage = messages.find((_, index) => index === currentTypingIndex);
    
    if (typingMessage && typingMessage.isTyping) {
      if (displayedText.length < typingMessage.content.length) {
        const timeout = setTimeout(() => {
          setDisplayedText(typingMessage.content.substring(0, displayedText.length + 1));
        }, typingSpeed);
        
        return () => clearTimeout(timeout);
      } else {
        setMessages(prevMessages => 
          prevMessages.map((msg, i) => 
            i === currentTypingIndex ? { ...msg, isTyping: false } : msg
          )
        );
        setCurrentTypingIndex(-1);
      }
    }
  }, [messages, currentTypingIndex, displayedText]);

  useEffect(() => {
    scrollToBottom();
  }, [messages, displayedText]);

  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  const shouldIncludeScreenshot = (text: string): boolean => {
    if (text.toLowerCase().includes('no screenshot') || 
        text.toLowerCase().includes('without screenshot') ||
        text.toLowerCase().includes('no image') ||
        text.toLowerCase().includes('不需要截圖') ||
        text.toLowerCase().includes('無需截圖')) {
      return false;
    }
    
    if (text.toLowerCase().includes('screenshot') || 
        text.toLowerCase().includes('capture') ||
        text.toLowerCase().includes('截圖') ||
        text.toLowerCase().includes('畫面')) {
      return true;
    }
    
    return includeScreenshot;
  };

  const handleAddSensitiveField = () => {
    setSensitiveData([...sensitiveData, { key: '', value: '' }]);
  };

  const handleRemoveSensitiveField = (index: number) => {
    const newFields = [...sensitiveData];
    newFields.splice(index, 1);
    setSensitiveData(newFields);
  };

  const handleSensitiveFieldChange = (index: number, field: 'key' | 'value', value: string) => {
    const newFields = [...sensitiveData];
    newFields[index][field] = value;
    setSensitiveData(newFields);
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!input.trim()) return;

    const sensitiveDataObj: Record<string, string> = {};
    sensitiveData.forEach(field => {
      if (field.key && field.value) {
        sensitiveDataObj[field.key] = field.value;
      }
    });

    const userMessage: Message = { role: 'user', content: input };
    setMessages(prev => [...prev, userMessage]);
    setInput('');
    setIsLoading(true);

    const needScreenshot = shouldIncludeScreenshot(input);

    try {
      const response = await axios.post('http://localhost:8081/execute-task', {
        task: input,
        include_screenshot: needScreenshot,
        sensitive_data: Object.keys(sensitiveDataObj).length > 0 ? sensitiveDataObj : undefined
      });

      const assistantMessage: Message = {
        role: 'assistant',
        content: response.data.message || 'Task executed successfully',
        screenshot: response.data.screenshot,
        isTyping: true
      };
      
      setMessages(prev => [...prev, assistantMessage]);
      setCurrentTypingIndex(messages.length + 1); 
      setDisplayedText('');
      
    } catch (error) {
      const errorMessage: Message = {
        role: 'assistant',
        content: 'Error executing task. Please try again.'
      };
      setMessages(prev => [...prev, errorMessage]);
    } finally {
      setIsLoading(false);
      inputRef.current?.focus();
    }
  };

  const toggleScreenshot = () => {
    setIncludeScreenshot(prev => !prev);
  };

  const toggleSensitiveFields = () => {
    setShowSensitiveFields(prev => !prev);
  };
  
  
  const handleTextareaChange = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    setInput(e.target.value);
  
    e.target.style.height = 'auto';
    e.target.style.height = `${Math.min(e.target.scrollHeight, 120)}px`;
  };
  
  
  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSubmit(e);
    }
  };

  return (
    <div className="chat-wrapper" ref={chatWrapperRef}>
      <div className="chat-container">
        {messages.length === 0 ? (
          <div className="welcome-container">
            <div className="logo-container">
              <div className="logo">🌐</div>
            </div>
            <h2 className="welcome-title">Browser Automation Assistant</h2>
            <p className="welcome-text">What would you like the browser to do for you today?</p>
            <div className="welcome-tips">
              <p>Examples you can try:</p>
              <ul>
                <li>Go to Google and search for "browser automation"</li>
                <li>Visit Wikipedia and search for "artificial intelligence"</li>
                <li>Go to weather.com and tell me the weather for New York</li>
                <li>Go to example.com and login with my_username and my_password (add these as sensitive data)</li>
              </ul>
            </div>
          </div>
        ) : (
          <div className="messages-container">
            {messages.map((message, index) => (
              <div 
                key={index} 
                className={`message-row ${message.role}`}
              >
                <div className="message-avatar">
                  {message.role === 'user' ? '👤' : '🌐'}
                </div>
                <div className="message-content-wrapper">
                  <div className="message-content">
                    {message.isTyping && index === currentTypingIndex 
                      ? displayedText
                      : message.content
                    }
                    {message.isTyping && index === currentTypingIndex && (
                      <span className="typing-cursor"></span>
                    )}
                  </div>
                  {message.screenshot && !message.isTyping && (
                    <div className="message-screenshot">
                      <img 
                        src={`data:image/png;base64,${message.screenshot}`} 
                        alt="Screenshot of task result" 
                        loading="lazy"
                      />
                    </div>
                  )}
                </div>
              </div>
            ))}
            {isLoading && (
              <div className="message-row assistant">
                <div className="message-avatar">🌐</div>
                <div className="message-content-wrapper">
                  <div className="message-content">
                    <div className="loading-indicator">
                      <span>.</span><span>.</span><span>.</span>
                    </div>
                    <div className="loading-text">Automating browser task...</div>
                  </div>
                </div>
              </div>
            )}
            <div ref={messagesEndRef} />
          </div>
        )}
      </div>
      
      <div className="input-container">
        {showSensitiveFields && (
          <div className="sensitive-data-container">
            <div className="sensitive-data-header">
              <h3>Sensitive Data</h3>
              <p className="sensitive-data-info">Add credentials or sensitive information that shouldn't be visible in your prompt</p>
            </div>
            {sensitiveData.map((field, index) => (
              <div key={index} className="sensitive-field-row">
                <input 
                  type="text"
                  placeholder="Key (e.g. username)"
                  value={field.key}
                  onChange={(e) => handleSensitiveFieldChange(index, 'key', e.target.value)}
                  className="sensitive-field"
                />
                <input 
                  type="password"
                  placeholder="Value (e.g. my_username)"
                  value={field.value}
                  onChange={(e) => handleSensitiveFieldChange(index, 'value', e.target.value)}
                  className="sensitive-field"
                />
                <button 
                  type="button"
                  onClick={() => handleRemoveSensitiveField(index)}
                  className="remove-field-button"
                >
                  ✕
                </button>
              </div>
            ))}
            <button 
              type="button"
              onClick={handleAddSensitiveField}
              className="add-field-button"
            >
              + Add Field
            </button>
          </div>
        )}
        
        <div className="input-wrapper">
          <form onSubmit={handleSubmit} className="input-form">
            <div className="input-options">
              <button 
                type="button" 
                onClick={toggleScreenshot}
                className={`option-button ${includeScreenshot ? 'active' : ''}`}
                title={includeScreenshot ? "Screenshots enabled" : "Screenshots disabled"}
              >
                {includeScreenshot ? "📷" : "🚫"}
              </button>
              <button
                type="button"
                onClick={toggleSensitiveFields}
                className={`option-button ${showSensitiveFields ? 'active' : ''}`}
                title={showSensitiveFields ? "Hide sensitive data fields" : "Show sensitive data fields"}
              >
                {showSensitiveFields ? "🔒" : "🔑"}
              </button>
            </div>
            <textarea
              ref={inputRef}
              value={input}
              onChange={handleTextareaChange}
              onKeyDown={handleKeyDown}
              placeholder="Enter your task..."
              disabled={isLoading}
              className="input-field"
              rows={1}
            />
            <button 
              type="submit" 
              disabled={isLoading || !input.trim()} 
              className={`submit-button ${input.trim() ? 'active' : ''}`}
            >
              <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" fill="currentColor" viewBox="0 0 256 256">
                <path d="M200,32V224a8,8,0,0,1-13.66,5.66l-72-72a8,8,0,0,1,0-11.32l72-72A8,8,0,0,1,200,32Z" transform="rotate(90 128 128)"></path>
              </svg>
            </button>
          </form>
        </div>
        
        <div className="input-settings">
          {!isLoading && (
            <div className="screenshot-status">
              {includeScreenshot ? 
                <span className="status-text">Screenshots: On</span> : 
                <span className="status-text">Screenshots: Off</span>
              }
              <span className="status-hint">
                (Add "no screenshot" to your request to disable for a single task)
              </span>
            </div>
          )}
          
          {sensitiveData.length > 0 && !showSensitiveFields && (
            <div className="sensitive-data-status">
              <span className="status-text">Sensitive fields: {sensitiveData.length}</span>
              <span className="status-hint">
                (Use the keys in your prompt, e.g. "login with username and password")
              </span>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};

export default Chat; 