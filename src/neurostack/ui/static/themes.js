// The themes the dashboard offers (issue #286): the two NeuroStack looks, defined in
// styles.css, then every theme in vendor/daisyui-themes.css (daisyUI 5, MIT).
export const THEMES = [
  ['neurostack', 'NeuroStack'], ['neurostack-dark', 'NeuroStack dark'],
  ...['light', 'dark', 'cupcake', 'bumblebee', 'emerald', 'corporate', 'synthwave', 'retro', 'cyberpunk',
    'valentine', 'halloween', 'garden', 'forest', 'aqua', 'lofi', 'pastel', 'fantasy', 'wireframe', 'black',
    'luxury', 'dracula', 'cmyk', 'autumn', 'business', 'acid', 'lemonade', 'night', 'coffee', 'winter', 'dim',
    'nord', 'sunset', 'caramellatte', 'abyss', 'silk']
    .map((name) => [name, name[0].toUpperCase() + name.slice(1)]),
];
// The stored choice; absent means "follow the OS" with the NeuroStack pair.
export const THEME_KEY = 'ns_daisy_theme';
