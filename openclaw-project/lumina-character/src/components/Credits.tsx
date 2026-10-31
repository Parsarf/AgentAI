/** The credit OpenMoji's license (CC BY-SA 4.0) requires for the bundled emoji artwork. Keep the sentence exactly as written. */
export const OPENMOJI_CREDIT = 'Emoji graphics by OpenMoji (https://openmoji.org), licensed under CC BY-SA 4.0 (https://creativecommons.org/licenses/by-sa/4.0/).';

const ext = { target: '_blank', rel: 'noopener noreferrer' } as const;

export default function Credits() {
  return (
    <section className="panel card" style={{ marginBottom: 14 }} aria-labelledby="credits-h"><h2 id="credits-h">Credits</h2>
      <p className="muted" style={{ marginTop: 10 }}>Emoji graphics by OpenMoji (<a href="https://openmoji.org" {...ext}>https://openmoji.org</a>), licensed under CC BY-SA 4.0 (<a href="https://creativecommons.org/licenses/by-sa/4.0/" {...ext}>https://creativecommons.org/licenses/by-sa/4.0/</a>).</p>
      <p className="faint" style={{ marginTop: 6 }}>Thinking orbs by Jakub Antalik (<a href="https://github.com/Jakubantalik/thinking-orbs" {...ext}>thinking-orbs</a>, MIT license).</p>
    </section>);
}
