// Shows a running restore in the #restoreProgress elements.
class RestoreProgressDisplay {
  constructor() {
    this.poll = null;
  }

  // Shows the spinner and polls for progress until stop().
  // Returns the id to send with the restore request.
  start(initialText) {
    const progressId = Array.from(crypto.getRandomValues(new Uint8Array(16)))
      .map(byte => byte.toString(16).padStart(2, '0'))
      .join('');

    document.getElementById('restoreProgressText').textContent = initialText;
    document.getElementById('restoreProgressBar').hidden = true;
    document.getElementById('restoreProgress').hidden = false;

    const poll = { active: true, timeoutId: null };
    this.poll = poll;

    const check = async () => {
      try {
        const response = await fetch(`/api/database/restore/progress/${progressId}`);
        const data = response.ok ? await response.json() : null;
        if (poll.active && data?.progress) {
          this.show(data.progress);
        }
      } catch (error) {
        // The restore request reports any real failure. Keep showing the spinner.
        console.warn('Could not read restore progress:', error);
      }
      if (poll.active) {
        poll.timeoutId = setTimeout(check, 1000);
      }
    };
    poll.timeoutId = setTimeout(check, 1000);

    return progressId;
  }

  show(progress) {
    const bar = document.getElementById('restoreProgressBar');
    const hasBytes = progress.bytes_total > 0;

    let text = progress.message;
    if (hasBytes) {
      const percent = Math.floor((progress.bytes_done / progress.bytes_total) * 100);
      bar.value = percent;
      text += ` (${percent}%)`;
    }
    bar.hidden = !hasBytes;
    document.getElementById('restoreProgressText').textContent = text;
  }

  stop() {
    if (this.poll) {
      this.poll.active = false;
      clearTimeout(this.poll.timeoutId);
      this.poll = null;
    }
    document.getElementById('restoreProgress').hidden = true;
  }
}
