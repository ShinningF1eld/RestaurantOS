
async function getData() {
  const response = await fetch("http://localhost:8000/api/test")

  if (!response.ok) {
    throw new Error("Failed to Fetch API");
  }

  return response.json()
}

export default async function Home() {

  const data = await getData()
 
  return (
    <main>
      <h1>RestaurantOS</h1>
      <p>{data.message}</p>
    </main>
  );
}