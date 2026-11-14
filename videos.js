// ====== APP SETTINGS (Muse edits this file when adding videos) ======
window.APP_CONFIG = {
  appName: "Video App",
  // Set to true once real videos are loaded, to show the 18+ entry gate
  ageGate: true
};

// ====== VIDEO LIST ======
// Each video comes from the video host (currently myUpload — myupload.us):
// after a video is ready there, copy its EMBED link and add one block below.
// Thumb: leave it out — a neutral placeholder is shown (real poster frames
// from adult videos must never be used as thumbnails in this app).
window.VIDEOS = [
  {
    title: "Video 1",
    embed: "https://myupload.us/embed/DufGxcN32J",
    duration: "5:25",
    size: "49 MB",
    portrait: true,
    category: "New"
  }
];
