export default {
    async scheduled(event, env, ctx) {
      const now = new Date();
      const hour = now.getUTCHours();
      const minute = now.getUTCMinutes();
      const dayOfWeek = now.getUTCDay(); // 0 = Sunday, 5 = Friday
  
      console.log(`Running scheduler check at ${hour}:${minute} UTC`);
  
      try {
        // Main game scrapers (09:00 and 21:00 UTC)
        if ((hour === 9 || hour === 21) && minute === 0) {
          console.log("Running game scrapers...");
          await Promise.all([
            fetch(`${env.API_URL}/run/crawler`, {
              method: 'POST',
              headers: {
                'Authorization': `Bearer ${env.API_KEY}`,
                'Content-Type': 'application/json'
              }
            }),
            fetch(`${env.API_URL}/run/epic`, {
              method: 'POST',
              headers: {
                'Authorization': `Bearer ${env.API_KEY}`,
                'Content-Type': 'application/json'
              }
            }),
            fetch(`${env.API_URL}/run/steam`, {
              method: 'POST',
              headers: {
                'Authorization': `Bearer ${env.API_KEY}`,
                'Content-Type': 'application/json'
              }
            }),
            fetch(`${env.API_URL}/run/gog_free`, {
              method: 'POST',
              headers: {
                'Authorization': `Bearer ${env.API_KEY}`,
                'Content-Type': 'application/json'
              }
            }),
            fetch(`${env.API_URL}/run/gog_giveaway`, {
              method: 'POST',
              headers: {
                'Authorization': `Bearer ${env.API_KEY}`,
                'Content-Type': 'application/json'
              }
            })
          ]);
        }
  
        // Newsletter new games (09:30 and 21:30 UTC)
        if ((hour === 9 || hour === 21) && minute === 30) {
          console.log("Running new games newsletter...");
          await fetch(`${env.API_URL}/run/newsletter_new_games`, {
            method: 'POST',
            headers: {
              'Authorization': `Bearer ${env.API_KEY}`,
              'Content-Type': 'application/json'
            }
          });
        }
  
        // Weekly newsletter (Friday 19:00 UTC)
        if (dayOfWeek === 5 && hour === 19 && minute === 0) {
          console.log("Running weekly newsletter...");
          await fetch(`${env.API_URL}/run/newsletter`, {
            method: 'POST',
            headers: {
              'Authorization': `Bearer ${env.API_KEY}`,
              'Content-Type': 'application/json'
            }
          });
        }
  
        // Cleanup (00:01 UTC)
        if (hour === 0 && minute === 1) {
          console.log("Running cleanup...");
          await fetch(`${env.API_URL}/run/cleanup`, {
            method: 'POST',
            headers: {
              'Authorization': `Bearer ${env.API_KEY}`,
              'Content-Type': 'application/json'
            }
          });
        }
      } catch (error) {
        console.error("Error in scheduler:", error);
      }
    }
  };