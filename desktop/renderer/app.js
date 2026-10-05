const reinstallBtn = document.getElementById('reinstallBtn');
const statusDiv = document.getElementById('status');
const statusMessage = document.getElementById('statusMessage');
const statusIcon = document.getElementById('statusIcon');
const outputDiv = document.getElementById('output');
const outputText = document.getElementById('outputText');
const connectionRadios = document.querySelectorAll('input[name="connection"]');

reinstallBtn.addEventListener('click', async () => {
  const wifiMode = document.querySelector('input[name="connection"]:checked').value === 'wifi';

  // UI 状態をリセット
  statusDiv.className = 'status loading';
  statusIcon.className = 'status-icon spinner';
  statusMessage.textContent = 'インストール中...';
  outputDiv.classList.add('hidden');
  reinstallBtn.disabled = true;
  connectionRadios.forEach(r => r.disabled = true);

  try {
    const result = await window.electronAPI.runAppleWatch({ wifi: wifiMode });

    if (result.success) {
      statusDiv.className = 'status success';
      statusIcon.className = 'status-icon';
      statusIcon.textContent = '✓';
      statusMessage.textContent = result.message;
    } else {
      statusDiv.className = 'status error';
      statusIcon.className = 'status-icon';
      statusIcon.textContent = '✕';
      statusMessage.textContent = result.message;

      // エラー出力を表示
      if (result.error) {
        outputDiv.classList.remove('hidden');
        outputText.value = result.error;
      }
    }
  } catch (error) {
    statusDiv.className = 'status error';
    statusIcon.className = 'status-icon';
    statusIcon.textContent = '✕';
    statusMessage.textContent = 'エラーが発生しました';

    outputDiv.classList.remove('hidden');
    outputText.value = error.message;
  } finally {
    reinstallBtn.disabled = false;
    connectionRadios.forEach(r => r.disabled = false);
  }
});
