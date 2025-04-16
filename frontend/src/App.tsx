import React from 'react';
import Chat from './components/Chat';
import './styles/App.css';
import './styles/Chat.css';

function App() {
  return (
    <div className="App">
      <header className="App-header">
        <h1>Browser Automation Assistant</h1>
      </header>
      <main className="App-main">
        <Chat />
      </main>
    </div>
  );
}

export default App;
